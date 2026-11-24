from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from nsrdp.db import Base, TimestampMixin, new_id
from nsrdp.tenancy.models import TenantScoped


class OutboxMessage(TenantScoped, TimestampMixin, Base):
    """A call to an external system that must not be lost.

    Written in the same transaction as the business change that causes it, then delivered
    by the dispatcher with retry and back-off. Status: pending -> delivered, or -> dead
    (routed to the connector owner as an exception).
    """

    __tablename__ = "connector_outbox"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connector: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), index=True, nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    response: Mapped[Any] = mapped_column(JSON, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner: Mapped[str] = mapped_column(String(256), nullable=False)
