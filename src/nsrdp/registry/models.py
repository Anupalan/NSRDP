from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from nsrdp.db import Base, TimestampMixin, new_id
from nsrdp.tenancy.models import TenantScoped


class RegistrySequence(Base):
    """National per-kind counter. Not tenant data: it only hands out numbers."""

    __tablename__ = "registry_sequences"

    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RegistryRecord(TenantScoped, TimestampMixin, Base):
    """Current state of a registered facility, vessel, worker, material or waste item.

    History lives in the event store (stream ``registry/<nsrdp_id>``).
    """

    __tablename__ = "registry_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    nsrdp_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)


class RegistryExternalId(TenantScoped, Base):
    """External identifiers (e.g. IMO number) that must be unique nationally.

    The unique constraint is enforced by the database across all tenants, so the same ship
    cannot be registered twice by two States.
    """

    __tablename__ = "registry_external_ids"
    __table_args__ = (UniqueConstraint("kind", "scheme", "value", name="uq_registry_external_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    scheme: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(String(256), nullable=False)
    nsrdp_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
