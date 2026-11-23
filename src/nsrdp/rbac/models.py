from __future__ import annotations

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from nsrdp.db import Base, TimestampMixin, new_id
from nsrdp.tenancy.models import TenantScoped


class RoleAssignment(TenantScoped, TimestampMixin, Base):
    """Principal P holds role R at tenant T (and therefore over T's subtree)."""

    __tablename__ = "role_assignments"
    __table_args__ = (
        UniqueConstraint("principal_id", "role", "tenant_id", name="uq_role_assignment"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    principal_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    granted_by: Mapped[str] = mapped_column(String(128), nullable=False)
