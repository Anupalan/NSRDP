from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    DDL,
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from nsrdp.db import Base, new_id, utcnow
from nsrdp.tenancy.models import TenantScoped


class Event(TenantScoped, Base):
    """One immutable fact in a stream (D3).

    Streams are e.g. ``("material", "<registry id>")`` or ``("audit", "rule:<id>")``.
    Each event carries the hash of the previous event in its stream, so any edit or
    deletion at the database level breaks the chain and is detectable.
    """

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("stream_type", "stream_id", "seq", name="uq_event_stream_seq"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    stream_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    stream_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    actor: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    corrects_event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id"), nullable=True)
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)


# Database-level append-only guard. The same SQL is applied by migration 0003 on PostgreSQL.
PG_APPEND_ONLY_FN = """
CREATE OR REPLACE FUNCTION nsrdp_events_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION USING MESSAGE = 'events are append-only (' || TG_OP || ')';
END;
$$ LANGUAGE plpgsql
"""
PG_APPEND_ONLY_TRIGGER = """
CREATE TRIGGER events_append_only BEFORE UPDATE OR DELETE ON events
FOR EACH ROW EXECUTE FUNCTION nsrdp_events_append_only()
"""
SQLITE_TRIGGERS = [
    "CREATE TRIGGER events_no_update BEFORE UPDATE ON events "
    "BEGIN SELECT RAISE(ABORT, 'events are append-only (UPDATE)'); END",
    "CREATE TRIGGER events_no_delete BEFORE DELETE ON events "
    "BEGIN SELECT RAISE(ABORT, 'events are append-only (DELETE)'); END",
]

for _sql in (PG_APPEND_ONLY_FN, PG_APPEND_ONLY_TRIGGER):
    event.listen(Event.__table__, "after_create", DDL(_sql).execute_if(dialect="postgresql"))
for _sql in SQLITE_TRIGGERS:
    event.listen(Event.__table__, "after_create", DDL(_sql).execute_if(dialect="sqlite"))
