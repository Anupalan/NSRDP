"""D2 / REC-01: rules are versioned data with a named approver; decisions record the version."""

from datetime import UTC, datetime, timedelta

import pytest

from nsrdp.rbac.policy import AccessDenied, SegregationOfDutiesViolation, assign_role
from nsrdp.rules import expr
from nsrdp.rules.service import (
    NoRuleInForce,
    RuleError,
    approve_rule,
    draft_rule,
    evaluate_rule,
    replay_decision,
    resolve_rule,
    retire_rule,
)
from nsrdp.tenancy.scope import system_scope

NOW = datetime(2027, 1, 1, tzinfo=UTC)
T1 = NOW + timedelta(days=1)
T2 = NOW + timedelta(days=30)

# Illustrative only: NOT a real regulatory rule. Thresholds are rule data, not code.
ELIGIBILITY = {
    "required_inputs": ["facility.authorization_valid", "vessel.has_ihm"],
    "logic": {"and": [{"var": "facility.authorization_valid"}, {"var": "vessel.has_ihm"}]},
}


@pytest.fixture
def people(session, tree, rbac_policy):
    with system_scope(session):
        for who, role, t in [
            ("author", "rules_author", "centre"),
            ("approver", "rules_approver", "centre"),
            ("s_author", "rules_author", "state_a"),
            ("s_approver", "rules_approver", "state_a"),
        ]:
            assign_role(
                session, rbac_policy, principal_id=who, role=role, tenant=tree[t], granted_by="root"
            )
    return tree


def _publish(session, rbac, tenant, definition, eff=T1, author="author", approver="approver"):
    with system_scope(session):
        rv = draft_rule(
            session,
            rbac,
            actor=author,
            tenant=tenant,
            rule_key="recycling.eligible",
            title="Eligibility",
            definition=definition,
            effective_from=eff,
        )
        return approve_rule(session, rbac, actor=approver, rule_version=rv, now=NOW)


def test_versions_increment_and_record_approver(session, people, rbac_policy):
    v1 = _publish(session, rbac_policy, people["centre"], ELIGIBILITY)
    v2 = _publish(session, rbac_policy, people["centre"], ELIGIBILITY, eff=T2)
    assert (v1.version, v2.version) == (1, 2)
    assert v1.approved_by == "approver" and v1.approved_at is not None


def test_author_cannot_approve(session, people, rbac_policy, tree):
    with system_scope(session):
        rv = draft_rule(
            session,
            rbac_policy,
            actor="author",
            tenant=tree["centre"],
            rule_key="k",
            title="t",
            definition=ELIGIBILITY,
            effective_from=T1,
        )
        with pytest.raises(SegregationOfDutiesViolation):
            approve_rule(session, rbac_policy, actor="author", rule_version=rv, now=NOW)


def test_approver_needs_permission_at_rule_tenant(session, people, rbac_policy, tree):
    with system_scope(session):
        rv = draft_rule(
            session,
            rbac_policy,
            actor="author",
            tenant=tree["centre"],
            rule_key="k",
            title="t",
            definition=ELIGIBILITY,
            effective_from=T1,
        )
        with pytest.raises(AccessDenied):
            approve_rule(session, rbac_policy, actor="s_approver", rule_version=rv, now=NOW)


def test_no_retroactive_rules(session, people, rbac_policy):
    with pytest.raises(RuleError):
        _publish(session, rbac_policy, people["centre"], ELIGIBILITY, eff=NOW - timedelta(days=1))


def test_approved_versions_are_immutable(session, people, rbac_policy):
    rv = _publish(session, rbac_policy, people["centre"], ELIGIBILITY)
    rv.definition = {"logic": True}
    with system_scope(session), pytest.raises(RuleError):
        session.flush()


def test_unknown_operator_rejected(session, people, rbac_policy, tree):
    with system_scope(session), pytest.raises(expr.RuleExpressionError):
        draft_rule(
            session,
            rbac_policy,
            actor="author",
            tenant=tree["centre"],
            rule_key="k",
            title="t",
            definition={"logic": {"__import__": ["os"]}},
            effective_from=T1,
        )


def test_decision_records_version_and_replays(session, people, rbac_policy, act_as, tree):
    v1 = _publish(session, rbac_policy, tree["centre"], ELIGIBILITY)
    act_as(tree["fac_a"])
    inputs = {"facility": {"authorization_valid": True}, "vessel": {"has_ihm": True}}
    d = evaluate_rule(
        session,
        rule_key="recycling.eligible",
        inputs=inputs,
        actor="officer",
        subject_ref="vessel:123",
        at=T1 + timedelta(hours=1),
    )
    assert d.outcome is True
    assert (d.rule_version_id, d.rule_version) == (v1.id, 1)
    assert d.tenant_id == tree["fac_a"].id
    assert replay_decision(session, d) is True


def test_effective_dates_select_version(session, people, rbac_policy, act_as, tree):
    _publish(session, rbac_policy, tree["centre"], {"logic": "v1"})
    _publish(session, rbac_policy, tree["centre"], {"logic": "v2"}, eff=T2)
    act_as(tree["state_a"])
    assert resolve_rule(session, "recycling.eligible", T1).definition["logic"] == "v1"
    assert resolve_rule(session, "recycling.eligible", T2).definition["logic"] == "v2"
    with pytest.raises(NoRuleInForce):
        resolve_rule(session, "recycling.eligible", NOW)


def test_state_override_applies_only_to_that_state(session, people, rbac_policy, act_as, tree):
    _publish(session, rbac_policy, tree["centre"], {"logic": "national"})
    _publish(
        session,
        rbac_policy,
        tree["state_a"],
        {"logic": "gujarat"},
        author="s_author",
        approver="s_approver",
    )
    act_as(tree["fac_a"])
    assert resolve_rule(session, "recycling.eligible", T1).definition["logic"] == "gujarat"
    act_as(tree["fac_b"])
    assert resolve_rule(session, "recycling.eligible", T1).definition["logic"] == "national"


def test_drafts_are_never_used(session, people, rbac_policy, act_as, tree):
    with system_scope(session):
        draft_rule(
            session,
            rbac_policy,
            actor="author",
            tenant=tree["centre"],
            rule_key="recycling.eligible",
            title="t",
            definition=ELIGIBILITY,
            effective_from=T1,
        )
    act_as(tree["state_a"])
    with pytest.raises(NoRuleInForce):
        resolve_rule(session, "recycling.eligible", T1)


def test_retire(session, people, rbac_policy, act_as, tree):
    rv = _publish(session, rbac_policy, tree["centre"], ELIGIBILITY)
    end = T2
    with system_scope(session):
        retire_rule(session, rbac_policy, actor="approver", rule_version=rv, at=end, now=NOW)
    act_as(tree["state_a"])
    with pytest.raises(NoRuleInForce):
        resolve_rule(session, "recycling.eligible", end + timedelta(seconds=1))


def test_missing_inputs(session, people, rbac_policy, act_as, tree):
    _publish(session, rbac_policy, tree["centre"], ELIGIBILITY)
    act_as(tree["state_a"])
    with pytest.raises(RuleError):
        evaluate_rule(session, rule_key="recycling.eligible", inputs={}, actor="x", at=T1)


@pytest.mark.parametrize(
    ("logic", "data", "expected"),
    [
        ({"==": [{"var": "a"}, 1]}, {"a": 1}, True),
        ({"<=": [0, {"var": "x"}, 10]}, {"x": 5}, True),
        ({"in": [{"var": "s"}, ["GJ", "MH"]]}, {"s": "KL"}, False),
        ({"if": [{">": [{"var": "n"}, 3]}, "big", "small"]}, {"n": 4}, "big"),
        ({"or": [False, {"var": ["z", 0]}, "x"]}, {}, "x"),
        ({"missing": ["a", "b.c"]}, {"a": 1, "b": {}}, ["b.c"]),
        ({"var": ["a.b", 9]}, {}, 9),
        ({"max": [1, {"+": [2, 3]}]}, {}, 5),
    ],
)
def test_expression_language(logic, data, expected):
    expr.validate(logic)
    assert expr.evaluate(logic, data) == expected
