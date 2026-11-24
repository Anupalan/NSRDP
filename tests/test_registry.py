"""REG-01..04: registry core, national ID scheme, no worker health fields (D5/WRK-03)."""

import copy

import pytest

from nsrdp.config import load_policy
from nsrdp.rbac.policy import AccessDenied, assign_role
from nsrdp.registry import service as reg
from nsrdp.registry.ids import IdScheme, InvalidIdentifier, imo_valid, mod97_valid
from nsrdp.tenancy.scope import system_scope

VESSEL = {"name": "MV Example", "imo_number": "9074729", "gross_tonnage": 25000}


@pytest.fixture
def policy():
    return reg.RegistryPolicy.load()


@pytest.fixture
def officers(session, tree, rbac_policy):
    with system_scope(session):
        assign_role(
            session,
            rbac_policy,
            principal_id="gj",
            role="registry_officer",
            tenant=tree["state_a"],
            granted_by="root",
        )
        assign_role(
            session,
            rbac_policy,
            principal_id="mh",
            role="registry_officer",
            tenant=tree["state_b"],
            granted_by="root",
        )
        assign_role(
            session,
            rbac_policy,
            principal_id="viewer",
            role="entity_user",
            tenant=tree["fac_a"],
            granted_by="root",
        )
    return tree


def _reg(session, policy, rbac, actor, tenant, kind, attrs):
    return reg.register(
        session, policy, rbac, actor=actor, tenant=tenant, kind=kind, attributes=attrs
    )


def test_ids_are_formatted_and_checked(policy):
    ids = policy.ids
    nid = ids.format("vessel", 42)
    assert nid.startswith("IN-VSL-00000042-")
    assert ids.parse(nid) == ("vessel", 42)
    tampered = nid.replace("00000042", "00000043")
    with pytest.raises(InvalidIdentifier):
        ids.parse(tampered)


def test_check_digits_catch_single_errors():
    body = "INWRK00001234"
    from nsrdp.registry.ids import mod97_check

    check = mod97_check(body)
    assert mod97_valid(body, check)
    for i, c in enumerate(body):
        for repl in "0123456789":
            if repl != c and c.isdigit():
                assert not mod97_valid(body[:i] + repl + body[i + 1 :], check)


def test_imo_check_digit():
    assert imo_valid("9074729") and imo_valid("IMO 9074729")
    assert not imo_valid("9074728") and not imo_valid("12345")


def test_register_vessel_emits_event_and_audit(session, policy, rbac_policy, officers, act_as):
    act_as(officers["state_a"])
    v = _reg(session, policy, rbac_policy, "gj", officers["state_a"], "vessel", VESSEL)
    assert policy.ids.parse(v.nsrdp_id)[0] == "vessel"
    events = reg.history(session, v.nsrdp_id)
    assert [e.event_type for e in events] == ["vessel.registered"]


def test_sequences_are_per_kind(session, policy, rbac_policy, officers, act_as):
    act_as(officers["state_a"])
    f1 = _reg(session, policy, rbac_policy, "gj", officers["fac_a"], "facility", {"name": "Y1"})
    f2 = _reg(session, policy, rbac_policy, "gj", officers["fac_a"], "facility", {"name": "Y2"})
    assert policy.ids.parse(f1.nsrdp_id)[1] + 1 == policy.ids.parse(f2.nsrdp_id)[1]


def test_same_imo_cannot_be_registered_by_two_states(
    session, policy, rbac_policy, officers, act_as
):
    act_as(officers["state_a"])
    _reg(session, policy, rbac_policy, "gj", officers["state_a"], "vessel", VESSEL)
    act_as(officers["state_b"])
    with pytest.raises(reg.DuplicateRecord):
        _reg(
            session,
            policy,
            rbac_policy,
            "mh",
            officers["state_b"],
            "vessel",
            {**VESSEL, "imo_number": "IMO 9074729"},
        )


def test_validation(session, policy, rbac_policy, officers, act_as):
    act_as(officers["state_a"])
    t = officers["state_a"]
    with pytest.raises(reg.RegistryError, match="invalid IMO"):
        _reg(session, policy, rbac_policy, "gj", t, "vessel", {**VESSEL, "imo_number": "9074720"})
    with pytest.raises(reg.RegistryError, match="unknown attributes"):
        _reg(session, policy, rbac_policy, "gj", t, "vessel", {**VESSEL, "colour": "red"})
    with pytest.raises(reg.RegistryError, match="required"):
        _reg(session, policy, rbac_policy, "gj", t, "facility", {})
    with pytest.raises(reg.RegistryError, match="must be number"):
        _reg(session, policy, rbac_policy, "gj", t, "vessel", {**VESSEL, "gross_tonnage": "big"})


def test_material_and_waste_link_to_origin_vessel(session, policy, rbac_policy, officers, act_as):
    act_as(officers["state_a"])
    v = _reg(session, policy, rbac_policy, "gj", officers["state_a"], "vessel", VESSEL)
    m = _reg(
        session,
        policy,
        rbac_policy,
        "gj",
        officers["fac_a"],
        "material",
        {"origin_vessel": v.nsrdp_id, "category": "ferrous"},
    )
    w = _reg(
        session,
        policy,
        rbac_policy,
        "gj",
        officers["fac_a"],
        "waste",
        {"origin_vessel": v.nsrdp_id, "waste_stream": "asbestos", "hazardous": True},
    )
    assert m.attributes["origin_vessel"] == w.attributes["origin_vessel"] == v.nsrdp_id
    with pytest.raises(reg.RegistryError, match="not a registered vessel"):
        _reg(
            session,
            policy,
            rbac_policy,
            "gj",
            officers["fac_a"],
            "material",
            {"origin_vessel": m.nsrdp_id, "category": "ferrous"},
        )


def test_worker_has_no_health_fields(session, policy, rbac_policy, officers, act_as):
    act_as(officers["state_a"])
    with pytest.raises(reg.RegistryError, match="unknown attributes"):
        _reg(
            session,
            policy,
            rbac_policy,
            "gj",
            officers["fac_a"],
            "worker",
            {"identity_ref": "idp:abc", "medical_fitness": "fit"},
        )
    w = _reg(
        session, policy, rbac_policy, "gj", officers["fac_a"], "worker", {"identity_ref": "idp:abc"}
    )
    assert w.nsrdp_id.startswith("IN-WRK-")


def test_config_cannot_add_worker_health_fields():
    cfg = copy.deepcopy(load_policy("registry"))
    cfg["kinds"]["worker"]["attributes"]["blood_group"] = {"type": "string"}
    with pytest.raises(reg.RegistryConfigError, match="D5"):
        reg.RegistryPolicy.from_dict(cfg)


def test_permission_and_scope(session, policy, rbac_policy, officers, act_as):
    act_as(officers["fac_a"])
    with pytest.raises(AccessDenied):
        _reg(session, policy, rbac_policy, "viewer", officers["fac_a"], "facility", {"name": "x"})
    with pytest.raises(AccessDenied):
        _reg(session, policy, rbac_policy, "mh", officers["fac_a"], "facility", {"name": "x"})
    act_as(officers["state_a"])
    f = _reg(session, policy, rbac_policy, "gj", officers["fac_a"], "facility", {"name": "Y"})
    act_as(officers["state_b"])
    assert reg.get(session, f.nsrdp_id) is None


def test_amend_keeps_history(session, policy, rbac_policy, officers, act_as):
    act_as(officers["state_a"])
    v = _reg(session, policy, rbac_policy, "gj", officers["state_a"], "vessel", VESSEL)
    reg.amend(
        session,
        policy,
        rbac_policy,
        actor="gj",
        record=v,
        changes={"flag_state": "PA"},
        reason="flag updated",
    )
    assert v.attributes["flag_state"] == "PA"
    assert [e.event_type for e in reg.history(session, v.nsrdp_id)] == [
        "vessel.registered",
        "vessel.amended",
    ]
    with pytest.raises(reg.RegistryError, match="cannot be amended"):
        reg.amend(
            session,
            policy,
            rbac_policy,
            actor="gj",
            record=v,
            changes={"imo_number": "9074729"},
            reason="x",
        )


def test_id_scheme_is_configuration():
    cfg = copy.deepcopy(load_policy("registry"))
    cfg["id_scheme"]["prefix"] = "DGMA"
    ids = IdScheme.from_config(cfg)
    assert ids.format("waste", 1).startswith("DGMA-WST-00000001-")
