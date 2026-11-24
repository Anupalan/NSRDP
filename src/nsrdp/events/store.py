"""Append-only event store (D3).

* ``append`` adds an event to a stream with the next sequence number and a hash chained to
  the previous event. ``expected_seq`` gives optimistic concurrency.
* Corrections are new events (``event_type="correction"``) that name the event they
  replace; nothing is ever updated or deleted (ORM listeners and DB triggers enforce it).
* ``effective_events`` applies corrections; ``project`` folds events into derived state.
* Evidence is referenced, not stored: each reference carries a URI and a SHA-256 digest of
  the file in the evidence vault (vault product and retention are TBC).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy import event as sa_event
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nsrdp.db import utcnow
from nsrdp.events.models import Event
from nsrdp.tenancy.scope import system_scope

CORRECTION = "correction"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

S = TypeVar("S")


class EventStoreError(ValueError):
    pass


class ConcurrencyConflict(EventStoreError):
    pass


class ChainBroken(EventStoreError):
    pass


def _iso(dt: datetime) -> str:
    dt = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="microseconds")


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_hash(e: Event) -> str:
    body = {
        "tenant_id": e.tenant_id,
        "stream_type": e.stream_type,
        "stream_id": e.stream_id,
        "seq": e.seq,
        "event_type": e.event_type,
        "payload": e.payload,
        "evidence": e.evidence,
        "actor": e.actor,
        "occurred_at": _iso(e.occurred_at),
        "corrects_event_id": e.corrects_event_id,
        "prev_hash": e.prev_hash,
    }
    return hashlib.sha256(_canonical(body).encode()).hexdigest()


def _check_evidence(evidence: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for ref in evidence:
        if not isinstance(ref, dict) or not ref.get("uri"):
            raise EventStoreError("evidence reference needs a 'uri'")
        if not _SHA256.match(str(ref.get("sha256", ""))):
            raise EventStoreError("evidence reference needs a lowercase hex 'sha256'")
        out.append(dict(ref))
    return out


def append(
    session: Session,
    *,
    tenant_id: str,
    stream_type: str,
    stream_id: str,
    event_type: str,
    payload: dict[str, Any] | None,
    actor: str,
    evidence: Iterable[dict[str, Any]] = (),
    occurred_at: datetime | None = None,
    corrects: Event | None = None,
    expected_seq: int | None = None,
) -> Event:
    # Sequence and chain are computed over the whole stream regardless of the caller's
    # scope; the new row itself is still checked against the scope on flush.
    with system_scope(session), session.no_autoflush:
        last = session.execute(
            select(Event)
            .where(Event.stream_type == stream_type, Event.stream_id == stream_id)
            .order_by(Event.seq.desc())
            .limit(1)
        ).scalar_one_or_none()
    current = last.seq if last else 0
    if expected_seq is not None and expected_seq != current:
        raise ConcurrencyConflict(f"stream at seq {current}, expected {expected_seq}")
    if last is not None and last.tenant_id != tenant_id:
        raise EventStoreError("a stream belongs to exactly one tenant")
    if corrects is not None:
        if (corrects.stream_type, corrects.stream_id) != (stream_type, stream_id):
            raise EventStoreError("a correction must be in the same stream as its target")
        if event_type != CORRECTION:
            raise EventStoreError(f"events that correct another must have type {CORRECTION!r}")
    elif event_type == CORRECTION:
        raise EventStoreError("a correction must name the event it corrects")

    ev = Event(
        tenant_id=tenant_id,
        stream_type=stream_type,
        stream_id=stream_id,
        seq=current + 1,
        event_type=event_type,
        payload=payload,
        evidence=_check_evidence(evidence),
        actor=actor,
        occurred_at=occurred_at or utcnow(),
        recorded_at=utcnow(),
        corrects_event_id=corrects.id if corrects else None,
        prev_hash=last.hash if last else None,
    )
    ev.hash = compute_hash(ev)
    session.add(ev)
    session.flush()
    return ev


def correct(
    session: Session,
    target: Event,
    *,
    payload: dict[str, Any] | None,
    actor: str,
    reason: str,
    evidence: Iterable[dict[str, Any]] = (),
) -> Event:
    """Record that ``target`` is replaced by ``payload`` (``None`` voids it)."""
    if not reason:
        raise EventStoreError("a correction needs a reason")
    return append(
        session,
        tenant_id=target.tenant_id,
        stream_type=target.stream_type,
        stream_id=target.stream_id,
        event_type=CORRECTION,
        payload={"reason": reason, "replacement": payload},
        actor=actor,
        evidence=evidence,
        corrects=target,
    )


def read_stream(session: Session, stream_type: str, stream_id: str) -> list[Event]:
    """Events of a stream visible in the session's scope, oldest first."""
    return list(
        session.execute(
            select(Event)
            .where(Event.stream_type == stream_type, Event.stream_id == stream_id)
            .order_by(Event.seq)
        ).scalars()
    )


def stream_head(session: Session, stream_type: str, stream_id: str) -> int:
    return session.execute(
        select(func.coalesce(func.max(Event.seq), 0)).where(
            Event.stream_type == stream_type, Event.stream_id == stream_id
        )
    ).scalar_one()


def verify_chain(events: list[Event]) -> None:
    """Raise :class:`ChainBroken` if any event was altered, removed or reordered."""
    prev: str | None = None
    for expected_seq, e in enumerate(events, start=1):
        if e.seq != expected_seq:
            raise ChainBroken(f"gap or reorder at seq {e.seq} (expected {expected_seq})")
        if e.prev_hash != prev:
            raise ChainBroken(f"prev_hash mismatch at seq {e.seq}")
        if compute_hash(e) != e.hash:
            raise ChainBroken(f"content hash mismatch at seq {e.seq}")
        prev = e.hash


def effective_events(events: list[Event]) -> list[tuple[Event, dict[str, Any]]]:
    """Original events with corrections applied, in original order.

    Returns ``(event, payload)`` pairs. A voided event is dropped. The latest correction of
    an event wins. Correction events themselves are not returned.
    """
    replacement: dict[str, dict[str, Any] | None] = {}
    for e in events:
        if e.event_type == CORRECTION and e.corrects_event_id:
            replacement[e.corrects_event_id] = (e.payload or {}).get("replacement")
    out = []
    for e in events:
        if e.event_type == CORRECTION:
            continue
        payload = replacement.get(e.id, e.payload) if e.id in replacement else e.payload
        if e.id in replacement and payload is None:
            continue
        out.append((e, payload or {}))
    return out


def project[S](
    events: list[Event], reducer: Callable[[S, Event, dict[str, Any]], S], initial: S
) -> S:
    """Derive state by folding effective events. State is never stored as truth."""
    state = initial
    for e, payload in effective_events(events):
        state = reducer(state, e, payload)
    return state


@sa_event.listens_for(Event, "before_update")
def _no_update(mapper, connection, target) -> None:
    raise EventStoreError("events are append-only")


@sa_event.listens_for(Event, "before_delete")
def _no_delete(mapper, connection, target) -> None:
    raise EventStoreError("events are append-only")
