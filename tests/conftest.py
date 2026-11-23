"""Shared fixtures. Set NSRDP_TEST_DATABASE_URL to run against PostgreSQL."""

from __future__ import annotations

import os

import pytest

from nsrdp.db import Base, make_engine, make_session_factory
from nsrdp.models import import_all_models
from nsrdp.rbac.policy import RbacPolicy
from nsrdp.tenancy.scope import Scope, set_scope, system_scope
from nsrdp.tenancy.service import TenancyPolicy, create_tenant

import_all_models()


@pytest.fixture
def engine():
    url = os.environ.get("NSRDP_TEST_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    eng = make_engine(url)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    return make_session_factory(engine)


@pytest.fixture
def session(session_factory):
    with session_factory() as s:
        yield s


@pytest.fixture
def tenancy_policy():
    return TenancyPolicy.load()


@pytest.fixture
def rbac_policy():
    return RbacPolicy.load()


@pytest.fixture
def tree(session, tenancy_policy):
    """Platform > Centre > {State A > Facility A1, State B > Facility B1}."""
    with system_scope(session):
        p = create_tenant(session, tenancy_policy, level="platform", code="IN", name="NSRDP")
        c = create_tenant(
            session, tenancy_policy, level="centre", code="DGMA", name="DGMA", parent=p
        )
        sa = create_tenant(
            session, tenancy_policy, level="state", code="GJ", name="Gujarat", parent=c
        )
        sb = create_tenant(
            session, tenancy_policy, level="state", code="MH", name="Maharashtra", parent=c
        )
        fa = create_tenant(
            session,
            tenancy_policy,
            level="entity",
            code="F1",
            name="Yard 1",
            parent=sa,
            entity_type="facility",
        )
        fb = create_tenant(
            session,
            tenancy_policy,
            level="entity",
            code="F2",
            name="Yard 2",
            parent=sb,
            entity_type="facility",
        )
        session.commit()
    return {"platform": p, "centre": c, "state_a": sa, "state_b": sb, "fac_a": fa, "fac_b": fb}


def scope_of(tenant) -> Scope:
    return Scope(tenant_id=tenant.id, tenant_path=tenant.tenant_path)


@pytest.fixture
def act_as(session):
    def _act(tenant):
        set_scope(session, scope_of(tenant))
        return session

    return _act
