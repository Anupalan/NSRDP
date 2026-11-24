"""Authorization and segregation of duties.

* Roles, their permissions and the tenant levels at which they may be granted are read
  from ``config/rbac.yaml``. Role names there are placeholders until the Centre/State
  operating model is agreed (TBC).
* A role held at tenant T applies to T and every tenant below it.
* Static SoD: conflicting roles may not be held by one principal in overlapping scope.
* Dynamic SoD: conflicting actions on one object must be done by different principals
  (e.g. the author of a rule version may not approve it).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nsrdp.config import load_policy
from nsrdp.events import audit
from nsrdp.rbac.models import RoleAssignment
from nsrdp.tenancy.models import Tenant
from nsrdp.tenancy.scope import system_scope


class AccessDenied(PermissionError):
    pass


class SegregationOfDutiesViolation(PermissionError):
    pass


class RbacConfigError(ValueError):
    pass


@dataclass(frozen=True)
class RoleDef:
    name: str
    permissions: frozenset[str]
    assignable_at: frozenset[str]


@dataclass(frozen=True)
class RbacPolicy:
    permissions: frozenset[str]
    roles: dict[str, RoleDef]
    conflicting_roles: tuple[frozenset[str], ...]
    conflicting_actions: tuple[frozenset[str], ...]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RbacPolicy:
        perms = frozenset(data.get("permissions", []))
        roles: dict[str, RoleDef] = {}
        for name, spec in (data.get("roles") or {}).items():
            rp = frozenset(spec.get("permissions", []))
            if rp - perms:
                raise RbacConfigError(f"role {name}: unknown permissions {sorted(rp - perms)}")
            roles[name] = RoleDef(name, rp, frozenset(spec.get("assignable_at", [])))
        sod = data.get("segregation_of_duties") or {}
        cr = tuple(frozenset(p) for p in sod.get("conflicting_roles", []))
        ca = tuple(frozenset(p) for p in sod.get("conflicting_actions", []))
        for pair in cr:
            if pair - roles.keys():
                raise RbacConfigError(f"SoD refers to unknown roles {sorted(pair - roles.keys())}")
        for pair in ca:
            if pair - perms:
                raise RbacConfigError(f"SoD refers to unknown permissions {sorted(pair - perms)}")
        return cls(perms, roles, cr, ca)

    @classmethod
    def load(cls) -> RbacPolicy:
        return cls.from_dict(load_policy("rbac"))


def _overlaps(a: str, b: str) -> bool:
    return a.startswith(b) or b.startswith(a)


def _assignments(session: Session, principal_id: str) -> list[RoleAssignment]:
    with system_scope(session):
        return list(
            session.execute(
                select(RoleAssignment).where(RoleAssignment.principal_id == principal_id)
            ).scalars()
        )


def assign_role(
    session: Session,
    policy: RbacPolicy,
    *,
    principal_id: str,
    role: str,
    tenant: Tenant,
    granted_by: str,
) -> RoleAssignment:
    spec = policy.roles.get(role)
    if spec is None:
        raise RbacConfigError(f"unknown role {role!r}")
    if tenant.level not in spec.assignable_at:
        raise AccessDenied(f"role {role!r} cannot be granted at level {tenant.level!r}")
    if granted_by == principal_id:
        raise SegregationOfDutiesViolation("a principal cannot grant a role to itself")
    for existing in _assignments(session, principal_id):
        if not _overlaps(existing.tenant_path, tenant.tenant_path):
            continue
        for pair in policy.conflicting_roles:
            if {existing.role, role} == pair:
                raise SegregationOfDutiesViolation(
                    f"{principal_id} holds {existing.role!r}, which conflicts with {role!r}"
                )
    ra = RoleAssignment(
        principal_id=principal_id, role=role, tenant_id=tenant.id, granted_by=granted_by
    )
    session.add(ra)
    session.flush()
    audit.record(
        session,
        tenant_id=tenant.id,
        actor=granted_by,
        action="role.granted",
        target_type="role_assignment",
        target_id=ra.id,
        details={"principal_id": principal_id, "role": role},
    )
    return ra


def has_permission(
    session: Session, policy: RbacPolicy, principal_id: str, permission: str, tenant_path: str
) -> bool:
    if permission not in policy.permissions:
        raise RbacConfigError(f"unknown permission {permission!r}")
    for ra in _assignments(session, principal_id):
        if tenant_path.startswith(ra.tenant_path):
            role = policy.roles.get(ra.role)
            if role and permission in role.permissions:
                return True
    return False


def authorize(
    session: Session, policy: RbacPolicy, principal_id: str, permission: str, tenant_path: str
) -> None:
    if not has_permission(session, policy, principal_id, permission, tenant_path):
        raise AccessDenied(f"{principal_id} lacks {permission} at {tenant_path}")


def ensure_distinct_actors(
    policy: RbacPolicy, prior: dict[str, str | None], action: str, actor: str
) -> None:
    """Dynamic SoD. ``prior`` maps permissions already exercised on an object to the actor."""
    for pair in policy.conflicting_actions:
        if action not in pair:
            continue
        for other in pair - {action}:
            if prior.get(other) == actor:
                raise SegregationOfDutiesViolation(
                    f"{actor} already performed {other!r}; cannot also perform {action!r}"
                )
