"""Enforce tenant scoping on every ORM query (PLT-01).

A session must carry a :class:`Scope` before it touches any tenant-owned table. The guard:

* adds ``tenant_path LIKE '<scope path>%'`` to every SELECT/UPDATE/DELETE on a
  :class:`~nsrdp.db.ScopedByPath` entity (including joins and relationship loads);
* refuses the query outright if no scope is set (fail closed);
* on flush, stamps ``tenant_path`` on new rows from their tenant and refuses rows that
  fall outside the scope or that try to change tenant.

``system_scope`` bypasses the filter. It exists for platform internals (bootstrap,
authorization lookups) and must never be reachable from a request handler.

Raw SQL (``text()``) is not covered; it is banned in domain code. A database-level
second layer (PostgreSQL row-level security) is an open follow-up, see docs/.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from nsrdp.db import ScopedByPath, new_id

SCOPE_KEY = "nsrdp_scope"


class TenantScopeError(PermissionError):
    """A row or query falls outside the session's tenant scope."""


class TenantScopeMissing(TenantScopeError):
    """A tenant-owned table was queried without a scope."""


@dataclass(frozen=True)
class Scope:
    tenant_id: str | None
    tenant_path: str
    system: bool = False

    def covers(self, path: str) -> bool:
        return self.system or path.startswith(self.tenant_path)


SYSTEM = Scope(tenant_id=None, tenant_path="/", system=True)


def set_scope(session: Session, scope: Scope) -> None:
    session.info[SCOPE_KEY] = scope


def get_scope(session: Session) -> Scope | None:
    return session.info.get(SCOPE_KEY)


@contextmanager
def system_scope(session: Session) -> Iterator[Session]:
    previous = session.info.get(SCOPE_KEY)
    session.info[SCOPE_KEY] = SYSTEM
    try:
        yield session
    finally:
        if previous is None:
            session.info.pop(SCOPE_KEY, None)
        else:
            session.info[SCOPE_KEY] = previous


def scope_for_tenant(session: Session, tenant_id: str) -> Scope:
    from nsrdp.tenancy.models import Tenant

    with system_scope(session):
        path = session.execute(
            select(Tenant.tenant_path).where(Tenant.id == tenant_id)
        ).scalar_one()
    return Scope(tenant_id=tenant_id, tenant_path=path)


def _touches_scoped(state: ORMExecuteState) -> bool:
    return any(issubclass(m.class_, ScopedByPath) for m in state.all_mappers)


def _on_execute(state: ORMExecuteState) -> None:
    if not (state.is_select or state.is_update or state.is_delete):
        return
    if not _touches_scoped(state):
        return
    scope = get_scope(state.session)
    if scope is None:
        raise TenantScopeMissing("query on tenant-owned data without a tenant scope")
    if scope.system:
        return
    # Paths are built only from generated UUIDs and "/", so no LIKE escaping is needed.
    prefix = scope.tenant_path
    state.statement = state.statement.options(
        with_loader_criteria(
            ScopedByPath,
            lambda cls: cls.tenant_path.startswith(prefix),
            include_aliases=True,
        )
    )


def _on_flush(session: Session, flush_context, instances) -> None:
    from nsrdp.tenancy.models import Tenant, TenantScoped

    pending = [o for o in session.new if isinstance(o, ScopedByPath)]
    dirty = [o for o in session.dirty if isinstance(o, ScopedByPath)]
    deleted = [o for o in session.deleted if isinstance(o, ScopedByPath)]
    if not (pending or dirty or deleted):
        return
    scope = get_scope(session)
    if scope is None:
        raise TenantScopeMissing("write to tenant-owned data without a tenant scope")

    for obj in pending:
        if isinstance(obj, Tenant):
            if obj.id is None:
                obj.id = new_id()
            if obj.parent_id is None:
                if not scope.system:
                    raise TenantScopeError("only the system scope may create a root tenant")
                parent_path = "/"
            else:
                parent_path = _load_tenant(session, obj.parent_id).tenant_path
                if not scope.covers(parent_path):
                    raise TenantScopeError("cannot create tenant outside scope")
            obj.tenant_path = f"{parent_path}{obj.id}/"
        elif isinstance(obj, TenantScoped):
            tenant = _load_tenant(session, obj.tenant_id)
            obj.tenant_path = tenant.tenant_path
            if not scope.covers(obj.tenant_path):
                raise TenantScopeError("cannot write row for a tenant outside scope")

    for obj in dirty:
        hist = inspect(obj).attrs
        for attr in ("tenant_path", "tenant_id", "parent_id"):
            if attr in hist and hist[attr].history.has_changes():
                raise TenantScopeError(f"{attr} is immutable")
        if not scope.covers(obj.tenant_path):
            raise TenantScopeError("cannot modify row outside scope")

    for obj in deleted:
        if not scope.covers(obj.tenant_path):
            raise TenantScopeError("cannot delete row outside scope")


def _load_tenant(session: Session, tenant_id: str):
    from nsrdp.tenancy.models import Tenant

    for obj in session.new:
        if isinstance(obj, Tenant) and obj.id == tenant_id and obj.tenant_path:
            return obj
    with system_scope(session), session.no_autoflush:
        tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        raise TenantScopeError(f"unknown tenant {tenant_id}")
    return tenant


_installed = False


def install_scope_guard() -> None:
    """Register the guard on all sessions. Idempotent."""
    global _installed
    if _installed:
        return
    event.listen(Session, "do_orm_execute", _on_execute)
    event.listen(Session, "before_flush", _on_flush)
    _installed = True


install_scope_guard()
