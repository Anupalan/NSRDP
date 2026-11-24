"""Audit log on top of the event store.

Every privileged action (role grants, rule drafts/approvals, registry writes, connector
operations) is recorded as an event in an ``audit`` stream keyed by the target object, so
the audit trail gets the same append-only and hash-chain guarantees.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nsrdp.events.models import Event
from nsrdp.events.store import append, read_stream

AUDIT = "audit"


def record(
    session: Session,
    *,
    tenant_id: str,
    actor: str,
    action: str,
    target_type: str,
    target_id: str,
    details: dict[str, Any] | None = None,
) -> Event:
    return append(
        session,
        tenant_id=tenant_id,
        stream_type=AUDIT,
        stream_id=f"{target_type}:{target_id}",
        event_type=action,
        payload=details or {},
        actor=actor,
    )


def trail(session: Session, target_type: str, target_id: str) -> list[Event]:
    return read_stream(session, AUDIT, f"{target_type}:{target_id}")


def by_actor(session: Session, actor: str) -> list[Event]:
    return list(
        session.execute(
            select(Event)
            .where(Event.stream_type == AUDIT, Event.actor == actor)
            .order_by(Event.recorded_at, Event.seq)
        ).scalars()
    )
