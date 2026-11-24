"""Tenant tree: Platform > Centre > State > Entity (levels are configuration, PLT-01)."""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from nsrdp.db import Base, ScopedByPath, TimestampMixin, new_id


class Tenant(ScopedByPath, TimestampMixin, Base):
    """A node in the tenant tree.

    ``tenant_path`` is this tenant's own materialised path (``/<root id>/.../<own id>/``),
    so the tenant table is scoped exactly like every other table: a principal acting in
    a State sees that State and everything below it, never its siblings or parents.
    """

    __tablename__ = "tenants"
    __table_args__ = (UniqueConstraint("parent_id", "code", name="uq_tenant_code_per_parent"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id"), nullable=True)
    level: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class TenantScoped(ScopedByPath):
    """Mixin for business rows owned by a tenant.

    ``tenant_path`` is copied from the owning tenant on insert (by the scope guard) and is
    immutable afterwards. Moving data between tenants is an open question (TBC) and is
    deliberately not supported.
    """

    @declared_attr
    def tenant_id(cls) -> Mapped[str]:  # noqa: N805
        return mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
