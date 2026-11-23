import pytest
from fastapi.testclient import TestClient

from nsrdp.api.app import create_app
from nsrdp.config import Settings
from nsrdp.rbac.policy import assign_role
from nsrdp.tenancy.scope import system_scope


@pytest.fixture
def client(session_factory, session, tree, rbac_policy):
    with system_scope(session):
        assign_role(
            session,
            rbac_policy,
            principal_id="s-officer",
            role="state_admin",
            tenant=tree["state_a"],
            granted_by="root",
        )
        session.commit()
    app = create_app(Settings(auth_mode="dev"), session_factory)
    return TestClient(app)


def test_health(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_tenants_scoped_to_acting_tenant(client, tree):
    r = client.get(
        "/tenants", headers={"X-NSRDP-Principal": "s-officer", "X-NSRDP-Tenant": tree["state_a"].id}
    )
    assert r.status_code == 200
    assert {t["code"] for t in r.json()} == {"GJ", "F1"}


def test_no_role_at_acting_tenant(client, tree):
    r = client.get(
        "/tenants", headers={"X-NSRDP-Principal": "s-officer", "X-NSRDP-Tenant": tree["state_b"].id}
    )
    assert r.status_code == 403


def test_auth_disabled_by_default(session_factory):
    c = TestClient(create_app(Settings(auth_mode="disabled"), session_factory))
    assert c.get("/tenants").status_code == 501
