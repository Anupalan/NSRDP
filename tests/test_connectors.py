"""D4 / REC-05: one hub, contracts enforced, queue + retry with back-off + reconcile."""

from datetime import UTC, datetime, timedelta

import pytest

from nsrdp.connectors.contract import Contract, ContractError, ContractViolation, load_all
from nsrdp.connectors.hub import ConnectorHub, HubConfigError
from nsrdp.connectors.outbox import backoff, dispatch_due, enqueue, reconcile, requeue
from nsrdp.connectors.stub import ConnectorRejected, ConnectorUnavailable, example_for
from nsrdp.connectors.stubgen import render
from nsrdp.events import audit

NOW = datetime(2027, 1, 1, tzinfo=UTC)
POLICY = {
    "defaults": {
        "max_attempts": 3,
        "base_delay_seconds": 10,
        "max_delay_seconds": 60,
        "jitter_ratio": 0.0,
    }
}
MSG = {
    "channel": "sms",
    "recipient_ref": "idp:1",
    "template": "certificate.expiry",
    "locale": "en",
    "params": {"days": 30},
}


@pytest.fixture
def hub():
    return ConnectorHub(load_all(), POLICY)


def _enqueue(session, hub, tenant, key="k1"):
    return enqueue(
        session,
        hub,
        tenant_id=tenant.id,
        connector="notifications",
        operation="send",
        payload=MSG,
        idempotency_key=key,
        now=NOW,
    )


def test_hub_validates_requests_and_responses(hub):
    assert hub.call("notifications", "send", MSG)["accepted"] is True
    with pytest.raises(ContractViolation):
        hub.call("notifications", "send", {**MSG, "channel": "fax"})
    hub.adapter("notifications").respond_with("send", {"accepted": True})
    with pytest.raises(ContractViolation, match="response"):
        hub.call("notifications", "send", MSG)
    with pytest.raises(HubConfigError):
        hub.call("payments", "charge", {})  # no contract yet: cannot be called at all


def test_contract_requires_owner():
    with pytest.raises(ContractError):
        Contract.from_dict(
            {
                "name": "x",
                "status": "candidate",
                "requirement": "INT-01",
                "operations": {"a": {"request": {}, "response": {}}},
            }
        )


def test_live_mode_needs_explicit_adapter(monkeypatch):
    monkeypatch.setenv("NSRDP_CONNECTOR_ESIGN_MODE", "live")
    hub = ConnectorHub(load_all(), POLICY)
    with pytest.raises(HubConfigError):
        hub.adapter("esign")


def test_enqueue_validates_and_records_owner(session, hub, tree, act_as):
    act_as(tree["fac_a"])
    msg = _enqueue(session, hub, tree["fac_a"])
    assert msg.owner == hub.owner("notifications") and msg.status == "pending"
    with pytest.raises(ContractViolation):
        enqueue(
            session,
            hub,
            tenant_id=tree["fac_a"].id,
            connector="notifications",
            operation="send",
            payload={},
            idempotency_key="bad",
        )


def test_delivery(session, hub, tree, act_as):
    act_as(tree["fac_a"])
    msg = _enqueue(session, hub, tree["fac_a"])
    r = dispatch_due(session, hub, now=NOW)
    assert r.delivered == [msg.id] and msg.status == "delivered" and msg.attempts == 1
    assert hub.adapter("notifications").calls[0][2] == "k1"  # idempotency key passed on


def test_retry_with_backoff_then_success(session, hub, tree, act_as):
    act_as(tree["fac_a"])
    stub = hub.adapter("notifications")
    stub.fail_next("send", ConnectorUnavailable("timeout"), ConnectorUnavailable("503"))
    msg = _enqueue(session, hub, tree["fac_a"])
    assert dispatch_due(session, hub, now=NOW).retrying == [msg.id]
    assert msg.next_attempt_at.replace(tzinfo=UTC) == NOW + timedelta(seconds=10)
    assert dispatch_due(session, hub, now=NOW + timedelta(seconds=5)).retrying == []  # not due
    t = NOW + timedelta(seconds=10)
    dispatch_due(session, hub, now=t)
    assert msg.next_attempt_at.replace(tzinfo=UTC) == t + timedelta(seconds=20)
    dispatch_due(session, hub, now=t + timedelta(seconds=20))
    assert msg.status == "delivered" and msg.attempts == 3


def test_gives_up_and_routes_exception_to_owner(session, hub, tree, act_as):
    act_as(tree["fac_a"])
    hub.adapter("notifications").fail_next("send", *[ConnectorUnavailable("down")] * 3)
    msg = _enqueue(session, hub, tree["fac_a"])
    t = NOW
    for _ in range(3):
        dispatch_due(session, hub, now=t)
        t += timedelta(minutes=5)
    assert msg.status == "dead" and msg.attempts == 3
    trail = audit.trail(session, "outbox", msg.id)
    assert trail[0].event_type == "connector.exception"
    assert trail[0].payload["owner"] == hub.owner("notifications")
    requeue(session, msg, now=t)
    dispatch_due(session, hub, now=t)
    assert msg.status == "delivered"


def test_permanent_failure_is_not_retried(session, hub, tree, act_as):
    act_as(tree["fac_a"])
    hub.adapter("notifications").fail_next("send", ConnectorRejected("invalid recipient"))
    msg = _enqueue(session, hub, tree["fac_a"])
    dispatch_due(session, hub, now=NOW)
    assert msg.status == "dead" and msg.attempts == 1


def test_reconcile_requeues_lost_messages(session, hub, tree, act_as):
    act_as(tree["fac_a"])
    a = _enqueue(session, hub, tree["fac_a"], "a")
    b = _enqueue(session, hub, tree["fac_a"], "b")
    dispatch_due(session, hub, now=NOW)
    stub = hub.adapter("notifications")
    stub.forget("b")
    stub.acknowledged.append("zzz")
    report = reconcile(session, hub, "notifications")
    assert report.missing_remote == ["b"] and report.unknown_remote == ["zzz"]
    assert (a.status, b.status) == ("delivered", "pending")
    dispatch_due(session, hub, now=datetime.now(UTC) + timedelta(days=3650))
    assert b.status == "delivered"


def test_outbox_is_tenant_scoped(session, hub, tree, act_as):
    from sqlalchemy import select

    from nsrdp.connectors.models import OutboxMessage

    act_as(tree["fac_a"])
    _enqueue(session, hub, tree["fac_a"])
    act_as(tree["state_b"])
    assert session.execute(select(OutboxMessage)).scalars().all() == []


def test_backoff_is_capped_and_jittered():
    p = {"base_delay_seconds": 10, "max_delay_seconds": 60, "jitter_ratio": 0.5}
    assert backoff(p, 1, lambda: 0.5) == timedelta(seconds=10)
    assert backoff(p, 10, lambda: 0.5) == timedelta(seconds=60)
    assert backoff(p, 1, lambda: 1.0) == timedelta(seconds=15)
    assert backoff(p, 1, lambda: 0.0) == timedelta(seconds=5)


def test_stub_generator_examples_validate():
    for c in load_all().values():
        out = render(c)
        for op, pair in out["operations"].items():
            c.check_request(op, pair["request"])
            c.check_response(op, pair["response"])
    assert example_for({"type": "array", "items": {"type": "integer"}, "minItems": 2}) == [0, 0]
