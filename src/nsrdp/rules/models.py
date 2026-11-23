from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from nsrdp.db import Base, TimestampMixin, new_id, utcnow
from nsrdp.tenancy.models import TenantScoped


class RuleVersion(TenantScoped, TimestampMixin, Base):
    """One immutable version of a rule (D2, REC-01).

    A rule is identified by ``rule_key`` and owned by a tenant: a national rule sits at the
    Centre, a State variation at the State. The most specific approved, effective version
    on the acting tenant's ancestor chain wins.
    """

    __tablename__ = "rule_versions"
    __table_args__ = (UniqueConstraint("tenant_id", "rule_key", "version", name="uq_rule_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    rule_key: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    authored_by: Mapped[str] = mapped_column(String(128), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Decision(TenantScoped, Base):
    """The record of one rule evaluation. Always names the exact rule version used."""

    __tablename__ = "rule_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    rule_key: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    rule_version_id: Mapped[str] = mapped_column(
        ForeignKey("rule_versions.id"), index=True, nullable=False
    )
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    subject_ref: Mapped[str | None] = mapped_column(String(256), index=True, nullable=True)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    outcome: Mapped[Any] = mapped_column(JSON, nullable=True)
    decided_by: Mapped[str] = mapped_column(String(128), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    evaluated_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
