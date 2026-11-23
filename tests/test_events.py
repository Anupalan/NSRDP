"""D3: append-only events with evidence; corrections are new events; state is derived."""

import hashlib

import pytest
from sqlalchemy import text

from nsrdp.events import audit
from nsrdp.events.models import Event
from nsrdp.events.store import (
    ChainBroken,
    ConcurrencyConflict,
    EventStoreError,
    append,
    correct,
    effective_events,
    project,
    read_stream,
    verify_chain,
)
from nsrdp.rbac.policy import assign_role
from nsrdp.tenancy.scope import TenantScopeError, system_scope

DOC = {"uri": "vault://weighbridge/slip-001.pdf", "sha256": hashlib.sha256(b"x").hexdigest()}


def _add(session, tenant, kind, payload, **kw):
    return append(
        session,
        tenant_id=tenant.id,
        stream_type="material",
        stream_id="M-1",
        event_type=kind,
        payload=payload,
        actor="officer",
        **kw,
    )


def _weight(state, e, payload):
    if e.event_type == "recovered":
        return state + payload["kg"]
    if e.event_type == "dispatched":
        return state - payload["kg"]
    return state


def test_append_chains_and_verifies(session, tree, act_as):
    act_as(tree["fac_a"])
    _add(session, tree["fac_a"], "recovered", {"kg": 1000}, evidence=[DOC])
    _add(session, tree["fac_a"], "dispatched", {"kg": 400})
    events = read_stream(session, "material", "M-1")
    assert [e.seq for e in events] == [1, 2]
    assert events[1].prev_hash == events[0].hash
    assert events[0].evidence == [DOC]
    verify_chain(events)
    assert project(events, _weight, 0) == 600


def test_correction_is_a_new_event(session, tree, act_as):
    act_as(tree["fac_a"])
    first = _add(session, tree["fac_a"], "recovered", {"kg": 1000})
    _add(session, tree["fac_a"], "dispatched", {"kg": 400})
    correct(
        session, first, payload={"kg": 900}, actor="supervisor", reason="re-weighed", evidence=[DOC]
    )
    events = read_stream(session, "material", "M-1")
    assert len(events) == 3 and events[0].payload == {"kg": 1000}  # original untouched
    assert project(events, _weight, 0) == 500
    verify_chain(events)


def test_void_by_correction(session, tree, act_as):
    act_as(tree["fac_a"])
    _add(session, tree["fac_a"], "recovered", {"kg": 1000})
    wrong = _add(session, tree["fac_a"], "dispatched", {"kg": 400})
    correct(session, wrong, payload=None, actor="supervisor", reason="duplicate entry")
    events = read_stream(session, "material", "M-1")
    assert [e.event_type for e, _ in effective_events(events)] == ["recovered"]


def test_orm_cannot_update_or_delete(session, tree, act_as):
    act_as(tree["fac_a"])
    ev = _add(session, tree["fac_a"], "recovered", {"kg": 1})
    ev.payload = {"kg": 2}
    with pytest.raises(EventStoreError):
        session.flush()
    session.rollback()


def test_database_rejects_raw_update_and_delete(session, tree, act_as):
    act_as(tree["fac_a"])
    _add(session, tree["fac_a"], "recovered", {"kg": 1})
    session.commit()
    for sql in ("UPDATE events SET actor = 'x'", "DELETE FROM events"):
        with pytest.raises(Exception, match="append-only"):
            session.execute(text(sql))
        session.rollback()


def test_tamper_is_detected(session, tree, act_as):
    act_as(tree["fac_a"])
    _add(session, tree["fac_a"], "recovered", {"kg": 1000})
    _add(session, tree["fac_a"], "dispatched", {"kg": 400})
    events = read_stream(session, "material", "M-1")
    session.expunge_all()
    events[0].payload = {"kg": 5}  # detached copy, simulating a row edited out of band
    with pytest.raises(ChainBroken):
        verify_chain(events)
    with pytest.raises(ChainBroken):
        verify_chain(events[1:])


def test_optimistic_concurrency(session, tree, act_as):
    act_as(tree["fac_a"])
    _add(session, tree["fac_a"], "recovered", {"kg": 1}, expected_seq=0)
    with pytest.raises(ConcurrencyConflict):
        _add(session, tree["fac_a"], "recovered", {"kg": 1}, expected_seq=0)


def test_evidence_must_have_digest(session, tree, act_as):
    act_as(tree["fac_a"])
    with pytest.raises(EventStoreError):
        _add(session, tree["fac_a"], "recovered", {"kg": 1}, evidence=[{"uri": "x"}])


def test_streams_are_tenant_scoped(session, tree, act_as):
    act_as(tree["fac_a"])
    _add(session, tree["fac_a"], "recovered", {"kg": 1})
    with pytest.raises(EventStoreError):  # same stream, other tenant
        _add(session, tree["fac_b"], "recovered", {"kg": 1})
    act_as(tree["state_b"])
    assert read_stream(session, "material", "M-1") == []
    with pytest.raises(TenantScopeError):
        append(
            session,
            tenant_id=tree["fac_a"].id,
            stream_type="material",
            stream_id="M-2",
            event_type="recovered",
            payload={},
            actor="x",
        )


def test_correction_rules(session, tree, act_as):
    act_as(tree["fac_a"])
    with pytest.raises(EventStoreError):
        _add(session, tree["fac_a"], "correction", {})
    ev = _add(session, tree["fac_a"], "recovered", {"kg": 1})
    with pytest.raises(EventStoreError):
        correct(session, ev, payload={}, actor="x", reason="")


def test_privileged_actions_are_audited(session, tree, rbac_policy, act_as):
    with system_scope(session):
        ra = assign_role(
            session,
            rbac_policy,
            principal_id="u1",
            role="entity_user",
            tenant=tree["fac_a"],
            granted_by="admin",
        )
    act_as(tree["state_a"])
    trail = audit.trail(session, "role_assignment", ra.id)
    assert [(e.event_type, e.actor) for e in trail] == [("role.granted", "admin")]
    assert audit.by_actor(session, "admin")[0].payload["principal_id"] == "u1"
    act_as(tree["state_b"])
    assert audit.trail(session, "role_assignment", ra.id) == []


def test_event_table_is_registered():
    assert Event.__tablename__ == "events"
