"""HTTP entry point. Every request runs in a session scoped to the caller's acting tenant."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy.orm import Session

from nsrdp.config import Settings, get_settings
from nsrdp.db import make_engine, make_session_factory
from nsrdp.rbac.policy import RbacPolicy, has_permission
from nsrdp.tenancy.scope import scope_for_tenant, set_scope
from nsrdp.tenancy.service import visible_tenants


@dataclass(frozen=True)
class Principal:
    id: str
    tenant_id: str


def create_app(settings: Settings | None = None, session_factory=None) -> FastAPI:
    settings = settings or get_settings()
    if session_factory is None:
        session_factory = make_session_factory(make_engine(settings.database_url))
    rbac = RbacPolicy.load()
    app = FastAPI(title="NSRDP platform core", version="0.1.0")

    def principal(
        x_nsrdp_principal: str | None = Header(default=None),
        x_nsrdp_tenant: str | None = Header(default=None),
    ) -> Principal:
        # The identity / e-KYC provider is TBC (integration #01). Until it is chosen the
        # only mode is a header stub for local development; anything else is refused.
        if settings.auth_mode != "dev":
            raise HTTPException(501, "identity provider not configured (TBC)")
        if not x_nsrdp_principal or not x_nsrdp_tenant:
            raise HTTPException(401, "missing principal or acting tenant")
        return Principal(x_nsrdp_principal, x_nsrdp_tenant)

    def scoped_session(p: Principal = Depends(principal)) -> Iterator[Session]:
        with session_factory() as session:
            scope = scope_for_tenant(session, p.tenant_id)
            if not has_permission(session, rbac, p.id, "tenant.read", scope.tenant_path):
                raise HTTPException(403, "no role at the acting tenant")
            set_scope(session, scope)
            yield session

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/tenants")
    def list_tenants(session: Session = Depends(scoped_session)):
        return [
            {"id": t.id, "level": t.level, "code": t.code, "name": t.name, "path": t.tenant_path}
            for t in visible_tenants(session)
        ]

    return app
