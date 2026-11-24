"""Tenant tree operations. Allowed levels and parent/child pairs come from config."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nsrdp.config import load_policy
from nsrdp.tenancy.models import Tenant


class TenantModelError(ValueError):
    pass


@dataclass(frozen=True)
class TenancyPolicy:
    levels: list[str]
    allowed_children: dict[str, list[str]]
    entity_types: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TenancyPolicy:
        levels = [lvl["name"] for lvl in data["levels"]]
        children = {lvl["name"]: list(lvl.get("children", [])) for lvl in data["levels"]}
        for parent, kids in children.items():
            unknown = set(kids) - set(levels)
            if unknown:
                raise TenantModelError(f"{parent}: unknown child levels {sorted(unknown)}")
        return cls(levels, children, list(data.get("entity_types", [])))

    @classmethod
    def load(cls) -> TenancyPolicy:
        return cls.from_dict(load_policy("tenancy"))

    @property
    def root_level(self) -> str:
        return self.levels[0]


def create_tenant(
    session: Session,
    policy: TenancyPolicy,
    *,
    level: str,
    code: str,
    name: str,
    parent: Tenant | None = None,
    entity_type: str | None = None,
) -> Tenant:
    if level not in policy.levels:
        raise TenantModelError(f"unknown tenant level {level!r}")
    if parent is None:
        if level != policy.root_level:
            raise TenantModelError(f"only {policy.root_level!r} may be a root tenant")
    elif level not in policy.allowed_children.get(parent.level, []):
        raise TenantModelError(f"{level!r} may not sit under {parent.level!r}")
    if entity_type is not None and entity_type not in policy.entity_types:
        raise TenantModelError(f"unknown entity type {entity_type!r}")
    tenant = Tenant(
        level=level,
        code=code,
        name=name,
        parent_id=parent.id if parent else None,
        entity_type=entity_type,
    )
    session.add(tenant)
    session.flush()
    return tenant


def visible_tenants(session: Session) -> list[Tenant]:
    return list(session.execute(select(Tenant).order_by(Tenant.tenant_path)).scalars())
