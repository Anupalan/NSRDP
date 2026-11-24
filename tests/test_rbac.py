"""REC-02: roles from configuration, hierarchical grants, segregation of duties."""

import pytest

from nsrdp.rbac.policy import (
    AccessDenied,
    RbacConfigError,
    RbacPolicy,
    SegregationOfDutiesViolation,
    assign_role,
    authorize,
    ensure_distinct_actors,
    has_permission,
)
from nsrdp.tenancy.scope import system_scope


@pytest.fixture
def grant(session, rbac_policy):
    def _grant(principal, role, tenant, by="admin"):
        with system_scope(session):
            return assign_role(
                session,
                rbac_policy,
                principal_id=principal,
                role=role,
                tenant=tenant,
                granted_by=by,
            )

    return _grant


def test_role_applies_to_subtree_only(session, tree, rbac_policy, grant):
    grant("officer", "registry_officer", tree["state_a"])
    assert has_permission(
        session, rbac_policy, "officer", "registry.write", tree["fac_a"].tenant_path
    )
    assert not has_permission(
        session, rbac_policy, "officer", "registry.write", tree["fac_b"].tenant_path
    )
    assert not has_permission(
        session, rbac_policy, "officer", "registry.write", tree["centre"].tenant_path
    )


def test_authorize_raises(session, tree, rbac_policy, grant):
    grant("viewer", "entity_user", tree["fac_a"])
    with pytest.raises(AccessDenied):
        authorize(session, rbac_policy, "viewer", "registry.write", tree["fac_a"].tenant_path)


def test_role_level_restriction(tree, grant):
    with pytest.raises(AccessDenied):
        grant("x", "platform_admin", tree["state_a"])


def test_no_self_grant(tree, grant):
    with pytest.raises(SegregationOfDutiesViolation):
        grant("x", "auditor", tree["centre"], by="x")


def test_static_sod_in_overlapping_scope(tree, grant):
    grant("alice", "rules_author", tree["centre"])
    with pytest.raises(SegregationOfDutiesViolation):
        grant("alice", "rules_approver", tree["state_a"])


def test_static_sod_allows_disjoint_scope(tree, grant):
    grant("bob", "rules_author", tree["state_a"])
    grant("bob", "rules_approver", tree["state_b"])


def test_dynamic_sod(rbac_policy):
    with pytest.raises(SegregationOfDutiesViolation):
        ensure_distinct_actors(rbac_policy, {"rules.author": "alice"}, "rules.approve", "alice")
    ensure_distinct_actors(rbac_policy, {"rules.author": "alice"}, "rules.approve", "bob")


def test_config_validation():
    with pytest.raises(RbacConfigError):
        RbacPolicy.from_dict({"permissions": ["a"], "roles": {"r": {"permissions": ["b"]}}})
    with pytest.raises(RbacConfigError):
        RbacPolicy.from_dict(
            {
                "permissions": ["a"],
                "roles": {},
                "segregation_of_duties": {"conflicting_roles": [["x", "y"]]},
            }
        )
