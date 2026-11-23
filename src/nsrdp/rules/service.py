"""Rule lifecycle and evaluation (D2, REC-01).

* ``draft_rule`` creates the next version of a rule as data. Logic is validated, never
  executed as code.
* ``approve_rule`` needs ``rules.approve`` at the rule's tenant and a different principal
  from the author (dynamic SoD). Approved versions are immutable.
* ``evaluate_rule`` resolves the version in force for the acting tenant at a point in time
  and writes a :class:`Decision` naming that exact version.
* ``replay_decision`` re-runs a past decision against its recorded version and inputs.
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from sqlalchemy import event, func, inspect, or_, select
from sqlalchemy.orm import Session

from nsrdp.db import utcnow
from nsrdp.rbac.policy import RbacPolicy, authorize, ensure_distinct_actors
from nsrdp.rules import expr
from nsrdp.rules.models import Decision, RuleVersion
from nsrdp.tenancy.models import Tenant
from nsrdp.tenancy.scope import get_scope, system_scope


class RuleError(ValueError):
    pass


class NoRuleInForce(RuleError):
    pass


def _validate_definition(definition: dict[str, Any]) -> None:
    if not isinstance(definition, dict) or "logic" not in definition:
        raise RuleError("definition must be an object with a 'logic' expression")
    expr.validate(definition["logic"])
    for name in definition.get("required_inputs", []):
        if not isinstance(name, str):
            raise RuleError("required_inputs must be a list of input paths")


def draft_rule(
    session: Session,
    rbac: RbacPolicy,
    *,
    actor: str,
    tenant: Tenant,
    rule_key: str,
    title: str,
    definition: dict[str, Any],
    effective_from: datetime,
    effective_to: datetime | None = None,
    legal_basis: str | None = None,
) -> RuleVersion:
    authorize(session, rbac, actor, "rules.author", tenant.tenant_path)
    _validate_definition(definition)
    if effective_to is not None and effective_to <= effective_from:
        raise RuleError("effective_to must be after effective_from")
    latest = session.execute(
        select(func.max(RuleVersion.version)).where(
            RuleVersion.tenant_id == tenant.id, RuleVersion.rule_key == rule_key
        )
    ).scalar()
    rv = RuleVersion(
        tenant_id=tenant.id,
        rule_key=rule_key,
        version=(latest or 0) + 1,
        title=title,
        legal_basis=legal_basis,
        definition=copy.deepcopy(definition),
        status="draft",
        authored_by=actor,
        effective_from=effective_from,
        effective_to=effective_to,
    )
    session.add(rv)
    session.flush()
    return rv


def approve_rule(
    session: Session,
    rbac: RbacPolicy,
    *,
    actor: str,
    rule_version: RuleVersion,
    now: datetime | None = None,
) -> RuleVersion:
    now = now or utcnow()
    if rule_version.status != "draft":
        raise RuleError(f"only drafts can be approved (status={rule_version.status})")
    ensure_distinct_actors(rbac, {"rules.author": rule_version.authored_by}, "rules.approve", actor)
    authorize(session, rbac, actor, "rules.approve", rule_version.tenant_path)
    if _aware(rule_version.effective_from) < now:
        raise RuleError("a rule cannot take effect before it is approved (no retroactive rules)")
    rule_version.status = "approved"
    rule_version.approved_by = actor
    rule_version.approved_at = now
    session.flush()
    return rule_version


def retire_rule(
    session: Session,
    rbac: RbacPolicy,
    *,
    actor: str,
    rule_version: RuleVersion,
    at: datetime,
    now: datetime | None = None,
) -> RuleVersion:
    """End an approved version's validity from ``at``. Only the end date may change."""
    authorize(session, rbac, actor, "rules.approve", rule_version.tenant_path)
    if rule_version.status != "approved":
        raise RuleError("only approved versions can be retired")
    if _aware(at) < (now or utcnow()):
        raise RuleError("cannot retire retroactively")
    rule_version.effective_to = at
    session.flush()
    return rule_version


def _aware(dt: datetime) -> datetime:
    # SQLite drops tz info; all stored times are UTC.
    from datetime import UTC

    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _ancestor_paths(path: str) -> list[str]:
    parts = [p for p in path.split("/") if p]
    return ["/" + "/".join(parts[: i + 1]) + "/" for i in range(len(parts))]


def resolve_rule(session: Session, rule_key: str, at: datetime) -> RuleVersion:
    """The approved version in force at ``at`` for the session's acting tenant.

    Rules are published policy, so a State may read rules owned by its Centre. Only the
    acting tenant's own ancestor chain is consulted; sibling States are never visible.
    """
    scope = get_scope(session)
    if scope is None or scope.system:
        raise RuleError("rule resolution needs an acting tenant scope")
    chain = _ancestor_paths(scope.tenant_path)
    with system_scope(session):
        candidates = list(
            session.execute(
                select(RuleVersion).where(
                    RuleVersion.rule_key == rule_key,
                    RuleVersion.status == "approved",
                    RuleVersion.tenant_path.in_(chain),
                    RuleVersion.effective_from <= at,
                    or_(RuleVersion.effective_to.is_(None), RuleVersion.effective_to > at),
                )
            ).scalars()
        )
    if not candidates:
        raise NoRuleInForce(f"no approved version of {rule_key!r} in force at {at.isoformat()}")
    candidates.sort(
        key=lambda r: (len(r.tenant_path), _aware(r.effective_from), r.version), reverse=True
    )
    return candidates[0]


def _run(rv: RuleVersion, inputs: dict[str, Any]) -> Any:
    missing = [
        p
        for p in rv.definition.get("required_inputs", [])
        if expr.evaluate({"missing": [p]}, inputs)
    ]
    if missing:
        raise RuleError(f"missing required inputs: {missing}")
    return expr.evaluate(rv.definition["logic"], inputs)


def evaluate_rule(
    session: Session,
    *,
    rule_key: str,
    inputs: dict[str, Any],
    actor: str,
    subject_ref: str | None = None,
    at: datetime | None = None,
) -> Decision:
    at = at or utcnow()
    rv = resolve_rule(session, rule_key, at)
    outcome = _run(rv, inputs)
    scope = get_scope(session)
    decision = Decision(
        tenant_id=scope.tenant_id,
        rule_key=rule_key,
        rule_version_id=rv.id,
        rule_version=rv.version,
        subject_ref=subject_ref,
        inputs=copy.deepcopy(inputs),
        outcome=outcome,
        decided_by=actor,
        evaluated_as_of=at,
    )
    session.add(decision)
    session.flush()
    return decision


def replay_decision(session: Session, decision: Decision) -> Any:
    with system_scope(session):
        rv = session.get(RuleVersion, decision.rule_version_id)
    return _run(rv, decision.inputs)


# Approved rule versions and decisions are immutable at the ORM layer.
_FROZEN_AFTER_APPROVAL = (
    "definition",
    "rule_key",
    "version",
    "effective_from",
    "authored_by",
    "approved_by",
    "approved_at",
    "title",
    "legal_basis",
)


@event.listens_for(RuleVersion, "before_update")
def _freeze_rule(mapper, connection, target: RuleVersion) -> None:
    state = inspect(target)
    was_approved = state.attrs.status.history.deleted == ["approved"] or (
        target.status == "approved" and not state.attrs.status.history.has_changes()
    )
    if not was_approved:
        return
    for name in _FROZEN_AFTER_APPROVAL:
        if state.attrs[name].history.has_changes():
            raise RuleError(f"approved rule versions are immutable ({name})")
    if state.attrs.status.history.has_changes():
        raise RuleError("approved rule versions cannot change status")


@event.listens_for(Decision, "before_update")
def _freeze_decision(mapper, connection, target: Decision) -> None:
    raise RuleError("decisions are immutable")


@event.listens_for(Decision, "before_delete")
def _no_delete_decision(mapper, connection, target: Decision) -> None:
    raise RuleError("decisions cannot be deleted")
