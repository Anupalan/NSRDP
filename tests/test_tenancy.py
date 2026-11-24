"""PLT-01: tenant scoping is enforced on every query and write."""

import pytest
from sqlalchemy import delete, select, update

from nsrdp.rbac.models import RoleAssignment
from nsrdp.tenancy.models import Tenant
from nsrdp.tenancy.scope import TenantScopeError, TenantScopeMissing, system_scope
from nsrdp.tenancy.service import TenancyPolicy, TenantModelError, create_tenant, visible_tenants


def test_hierarchy_paths(tree):
    p, c, sa, fa = tree["platform"], tree["centre"], tree["state_a"], tree["fac_a"]
    assert p.tenant_path == f"/{p.id}/"
    assert fa.tenant_path == f"/{p.id}/{c.id}/{sa.id}/{fa.id}/"


def test_query_without_scope_fails_closed(session, tree):
    session.info.clear()
    with pytest.raises(TenantScopeMissing):
        session.execute(select(Tenant)).all()


def test_state_sees_only_own_subtree(session, tree, act_as):
    act_as(tree["state_a"])
    codes = {t.code for t in visible_tenants(session)}
    assert codes == {"GJ", "F1"}


def test_centre_sees_all_states(session, tree, act_as):
    act_as(tree["centre"])
    assert {t.code for t in visible_tenants(session)} == {"DGMA", "GJ", "MH", "F1", "F2"}


def test_get_by_id_outside_scope_returns_nothing(session, tree, act_as):
    other = tree["fac_b"].id
    session.expunge_all()
    act_as(tree["state_a"])
    assert session.execute(select(Tenant).where(Tenant.id == other)).scalar_one_or_none() is None


def test_bulk_update_and_delete_are_scoped(session, tree, act_as):
    session.expunge_all()
    act_as(tree["state_a"])
    session.execute(
        update(Tenant).values(name="renamed").execution_options(synchronize_session=False)
    )
    session.execute(delete(RoleAssignment))
    with system_scope(session):
        names = {t.code: t.name for t in session.execute(select(Tenant)).scalars()}
    assert names["F1"] == "renamed"
    assert names["F2"] == "Yard 2"
    assert names["IN"] == "NSRDP"


def test_cannot_create_child_outside_scope(session, tree, act_as, tenancy_policy):
    act_as(tree["state_a"])
    with pytest.raises(TenantScopeError):
        create_tenant(
            session,
            tenancy_policy,
            level="entity",
            code="X",
            name="x",
            parent=tree["state_b"],
            entity_type="facility",
        )


def test_cannot_create_root_without_system_scope(session, tree, act_as, tenancy_policy):
    act_as(tree["platform"])
    with pytest.raises(TenantScopeError):
        create_tenant(session, tenancy_policy, level="platform", code="P2", name="p2")


def test_cannot_write_row_for_foreign_tenant(session, tree, act_as):
    act_as(tree["state_a"])
    session.add(
        RoleAssignment(
            principal_id="u", role="entity_user", tenant_id=tree["fac_b"].id, granted_by="g"
        )
    )
    with pytest.raises(TenantScopeError):
        session.flush()


def test_tenant_is_immutable(session, tree, act_as):
    act_as(tree["centre"])
    ra = RoleAssignment(
        principal_id="u", role="entity_user", tenant_id=tree["fac_a"].id, granted_by="g"
    )
    session.add(ra)
    session.flush()
    ra.tenant_id = tree["fac_b"].id
    with pytest.raises(TenantScopeError):
        session.flush()


def test_level_rules_come_from_config(session, tree, tenancy_policy):
    with system_scope(session), pytest.raises(TenantModelError):
        create_tenant(
            session, tenancy_policy, level="state", code="X", name="x", parent=tree["fac_a"]
        )


def test_alternative_hierarchy_is_config_only(session):
    policy = TenancyPolicy.from_dict(
        {
            "levels": [
                {"name": "national", "children": ["region"]},
                {"name": "region", "children": []},
            ]
        }
    )
    with system_scope(session):
        n = create_tenant(session, policy, level="national", code="N", name="n")
        r = create_tenant(session, policy, level="region", code="R", name="r", parent=n)
    assert r.tenant_path.startswith(n.tenant_path)
