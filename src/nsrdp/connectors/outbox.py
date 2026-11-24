"""Reliable delivery to external systems: queue, retry with back-off, reconcile (REC-05).

External outages must not lose a transaction:

1. ``enqueue`` writes an :class:`OutboxMessage` in the caller's transaction (validated
   against the contract), so the business change and the intent to notify commit together.
2. ``dispatch_due`` (run by a worker) delivers due messages through the hub. Transient
   failures are retried with exponential back-off and jitter; permanent failures, or
   running out of attempts, mark the message ``dead`` and raise an exception item to the
   connector's owner (an audit event ``connector.exception``).
3. ``reconcile`` asks the remote side which idempotency keys it holds and re-queues any
   delivered message the remote does not know about.

Retry numbers come from ``config/connectors.yaml`` (SLA targets are TBC).
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nsrdp.connectors.contract import ContractViolation
from nsrdp.connectors.hub import ConnectorHub
from nsrdp.connectors.models import OutboxMessage
from nsrdp.connectors.stub import ConnectorRejected
from nsrdp.db import utcnow
from nsrdp.events import audit
from nsrdp.tenancy.scope import system_scope


def enqueue(
    session: Session,
    hub: ConnectorHub,
    *,
    tenant_id: str,
    connector: str,
    operation: str,
    payload: dict[str, Any],
    idempotency_key: str,
    now: datetime | None = None,
) -> OutboxMessage:
    hub.contracts[connector].check_request(operation, payload)
    msg = OutboxMessage(
        tenant_id=tenant_id,
        connector=connector,
        operation=operation,
        payload=payload,
        idempotency_key=idempotency_key,
        status="pending",
        attempts=0,
        next_attempt_at=now or utcnow(),
        owner=hub.owner(connector),
    )
    session.add(msg)
    session.flush()
    return msg


def backoff(policy: dict[str, Any], attempts: int, rand: Callable[[], float]) -> timedelta:
    base = float(policy["base_delay_seconds"])
    cap = float(policy["max_delay_seconds"])
    delay = min(cap, base * (2 ** (attempts - 1)))
    jitter = float(policy.get("jitter_ratio", 0)) * delay
    return timedelta(seconds=max(0.0, delay + (rand() * 2 - 1) * jitter))


@dataclass
class DispatchResult:
    delivered: list[str] = field(default_factory=list)
    retrying: list[str] = field(default_factory=list)
    dead: list[str] = field(default_factory=list)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def dispatch_due(
    session: Session,
    hub: ConnectorHub,
    *,
    now: datetime | None = None,
    limit: int = 100,
    rand: Callable[[], float] = random.random,
) -> DispatchResult:
    """Deliver due messages for all tenants. Platform worker only (system scope)."""
    now = now or utcnow()
    result = DispatchResult()
    with system_scope(session):
        due = list(
            session.execute(
                select(OutboxMessage)
                .where(OutboxMessage.status == "pending", OutboxMessage.next_attempt_at <= now)
                .order_by(OutboxMessage.next_attempt_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).scalars()
        )
        for msg in due:
            _deliver(session, hub, msg, now, rand, result)
        session.flush()
    return result


def _deliver(session, hub, msg, now, rand, result) -> None:
    policy = hub.retry_policy(msg.connector)
    msg.attempts += 1
    try:
        msg.response = hub.call(msg.connector, msg.operation, msg.payload, msg.idempotency_key)
    except (ConnectorRejected, ContractViolation) as exc:
        _dead(session, msg, f"permanent: {exc}", result)
        return
    except Exception as exc:  # noqa: BLE001 - any other failure is treated as transient
        if msg.attempts >= int(policy["max_attempts"]):
            _dead(session, msg, f"gave up after {msg.attempts} attempts: {exc}", result)
            return
        msg.last_error = str(exc)
        msg.next_attempt_at = now + backoff(policy, msg.attempts, rand)
        result.retrying.append(msg.id)
        return
    msg.status = "delivered"
    msg.delivered_at = now
    msg.last_error = None
    result.delivered.append(msg.id)


def _dead(session: Session, msg: OutboxMessage, reason: str, result: DispatchResult) -> None:
    msg.status = "dead"
    msg.last_error = reason
    result.dead.append(msg.id)
    audit.record(
        session,
        tenant_id=msg.tenant_id,
        actor="system:connector-dispatcher",
        action="connector.exception",
        target_type="outbox",
        target_id=msg.id,
        details={
            "connector": msg.connector,
            "operation": msg.operation,
            "owner": msg.owner,
            "reason": reason,
            "idempotency_key": msg.idempotency_key,
        },
    )


def requeue(session: Session, msg: OutboxMessage, *, now: datetime | None = None) -> None:
    """Owner action after fixing the cause of a dead message."""
    msg.status = "pending"
    msg.attempts = 0
    msg.next_attempt_at = now or utcnow()
    session.flush()


@dataclass
class ReconcileReport:
    connector: str
    missing_remote: list[str]
    unknown_remote: list[str]


def reconcile(
    session: Session, hub: ConnectorHub, connector: str, *, since: datetime | None = None
) -> ReconcileReport:
    """Compare what we delivered with what the remote holds; re-queue what it lost."""
    contract = hub.contracts[connector]
    if contract.reconcile_operation is None:
        raise ValueError(f"{connector}: contract defines no reconcile operation")
    request: dict[str, Any] = {}
    if since is not None:
        request["since"] = _aware(since).isoformat()
    remote = set(hub.call(connector, contract.reconcile_operation, request)["keys"])
    with system_scope(session):
        q = select(OutboxMessage).where(
            OutboxMessage.connector == connector, OutboxMessage.status == "delivered"
        )
        if since is not None:
            q = q.where(OutboxMessage.delivered_at >= since)
        delivered = list(session.execute(q).scalars())
        local = {m.idempotency_key for m in delivered}
        missing = sorted(local - remote)
        for m in delivered:
            if m.idempotency_key in missing:
                requeue(session, m)
        unknown = sorted(remote - local - _all_keys(session, connector))
    return ReconcileReport(connector, missing, unknown)


def _all_keys(session: Session, connector: str) -> set[str]:
    return set(
        session.execute(
            select(OutboxMessage.idempotency_key).where(OutboxMessage.connector == connector)
        ).scalars()
    )
