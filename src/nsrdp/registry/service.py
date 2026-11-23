"""Registry core (REG-01..04): register and amend records with national identifiers.

Attribute sets per kind come from ``config/registry.yaml``. Unknown attributes are
rejected, so fields that are not agreed (notably worker health data, WRK-03 / D5) cannot
enter through the payload either.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from nsrdp.config import load_policy
from nsrdp.events import audit
from nsrdp.events.store import append, read_stream
from nsrdp.rbac.policy import RbacPolicy, authorize
from nsrdp.registry.ids import IdScheme, imo_valid
from nsrdp.registry.models import RegistryExternalId, RegistryRecord, RegistrySequence
from nsrdp.tenancy.models import Tenant
from nsrdp.tenancy.scope import system_scope

_TYPES = {"string": str, "number": (int, float), "boolean": bool, "integer": int}


class RegistryError(ValueError):
    pass


class DuplicateRecord(RegistryError):
    pass


class RegistryConfigError(ValueError):
    pass


@dataclass(frozen=True)
class FieldDef:
    name: str
    type: str
    required: bool
    validator: str | None


@dataclass(frozen=True)
class KindDef:
    name: str
    fields: dict[str, FieldDef]
    external_ids: tuple[str, ...]


@dataclass(frozen=True)
class RegistryPolicy:
    ids: IdScheme
    kinds: dict[str, KindDef]

    @classmethod
    def from_dict(cls, cfg: dict[str, Any]) -> RegistryPolicy:
        forbidden = [
            re.compile(p, re.I) for p in cfg.get("worker_forbidden_attribute_patterns", [])
        ]
        kinds: dict[str, KindDef] = {}
        for name, spec in cfg["kinds"].items():
            fields = {}
            for fname, f in (spec.get("attributes") or {}).items():
                if f.get("type") not in _TYPES:
                    raise RegistryConfigError(f"{name}.{fname}: unknown type {f.get('type')!r}")
                if name == "worker" and any(p.search(fname) for p in forbidden):
                    raise RegistryConfigError(
                        f"worker.{fname}: health-related worker fields are blocked until the "
                        "privacy position (D5, WRK-03) is decided"
                    )
                fields[fname] = FieldDef(
                    fname, f["type"], bool(f.get("required")), f.get("validator")
                )
            ext = tuple(spec.get("external_ids") or ())
            if set(ext) - fields.keys():
                raise RegistryConfigError(f"{name}: external_ids must be attributes")
            kinds[name] = KindDef(name, fields, ext)
        return cls(IdScheme.from_config(cfg), kinds)

    @classmethod
    def load(cls) -> RegistryPolicy:
        return cls.from_dict(load_policy("registry"))


def _validate(
    session: Session, policy: RegistryPolicy, kind: KindDef, attrs: dict[str, Any]
) -> dict[str, Any]:
    unknown = set(attrs) - kind.fields.keys()
    if unknown:
        raise RegistryError(f"{kind.name}: unknown attributes {sorted(unknown)}")
    for f in kind.fields.values():
        if f.name not in attrs or attrs[f.name] is None:
            if f.required:
                raise RegistryError(f"{kind.name}.{f.name} is required")
            continue
        value = attrs[f.name]
        if (isinstance(value, bool) and f.type != "boolean") or not isinstance(
            value, _TYPES[f.type]
        ):
            raise RegistryError(f"{kind.name}.{f.name} must be {f.type}")
        if f.validator == "imo" and not imo_valid(value):
            raise RegistryError(f"{kind.name}.{f.name}: invalid IMO number {value!r}")
        if f.validator == "vessel_ref":
            target = _get_any_scope(session, value)
            if target is None or target.kind != "vessel":
                raise RegistryError(f"{kind.name}.{f.name}: {value!r} is not a registered vessel")
    return dict(attrs)


def _get_any_scope(session: Session, nsrdp_id: str) -> RegistryRecord | None:
    # Origin vessels are national records (REG-02); a facility in one State may recycle a
    # vessel registered elsewhere. Only existence and kind are checked here.
    with system_scope(session), session.no_autoflush:
        return session.execute(
            select(RegistryRecord).where(RegistryRecord.nsrdp_id == nsrdp_id)
        ).scalar_one_or_none()


def _next_number(session: Session, kind: str) -> int:
    seq = session.execute(
        select(RegistrySequence).where(RegistrySequence.kind == kind).with_for_update()
    ).scalar_one_or_none()
    if seq is None:
        seq = RegistrySequence(kind=kind, last_value=0)
        session.add(seq)
    seq.last_value += 1
    session.flush()
    return seq.last_value


def register(
    session: Session,
    policy: RegistryPolicy,
    rbac: RbacPolicy,
    *,
    actor: str,
    tenant: Tenant,
    kind: str,
    attributes: dict[str, Any],
    evidence: list[dict[str, Any]] | None = None,
) -> RegistryRecord:
    kdef = policy.kinds.get(kind)
    if kdef is None:
        raise RegistryError(f"unknown registry kind {kind!r}")
    authorize(session, rbac, actor, "registry.write", tenant.tenant_path)
    attrs = _validate(session, policy, kdef, attributes)
    nsrdp_id = policy.ids.format(kind, _next_number(session, kind))
    record = RegistryRecord(
        nsrdp_id=nsrdp_id, kind=kind, tenant_id=tenant.id, attributes=attrs, created_by=actor
    )
    session.add(record)
    try:
        with session.begin_nested():
            for scheme in kdef.external_ids:
                if attrs.get(scheme) is not None:
                    session.add(
                        RegistryExternalId(
                            kind=kind,
                            scheme=scheme,
                            value=_norm(scheme, attrs[scheme]),
                            nsrdp_id=nsrdp_id,
                            tenant_id=tenant.id,
                        )
                    )
            session.flush()
    except IntegrityError as exc:
        raise DuplicateRecord(
            f"{kind} with the same {', '.join(kdef.external_ids)} is already registered"
        ) from exc
    append(
        session,
        tenant_id=tenant.id,
        stream_type="registry",
        stream_id=nsrdp_id,
        event_type=f"{kind}.registered",
        payload=attrs,
        actor=actor,
        evidence=evidence or [],
    )
    audit.record(
        session,
        tenant_id=tenant.id,
        actor=actor,
        action="registry.registered",
        target_type="registry",
        target_id=nsrdp_id,
        details={"kind": kind},
    )
    return record


def amend(
    session: Session,
    policy: RegistryPolicy,
    rbac: RbacPolicy,
    *,
    actor: str,
    record: RegistryRecord,
    changes: dict[str, Any],
    reason: str,
    evidence: list[dict[str, Any]] | None = None,
) -> RegistryRecord:
    if not reason:
        raise RegistryError("an amendment needs a reason")
    authorize(session, rbac, actor, "registry.write", record.tenant_path)
    kdef = policy.kinds[record.kind]
    frozen = set(changes) & set(kdef.external_ids)
    if frozen:
        raise RegistryError(f"external identifiers cannot be amended: {sorted(frozen)}")
    merged = _validate(session, policy, kdef, {**record.attributes, **changes})
    record.attributes = merged
    session.flush()
    append(
        session,
        tenant_id=record.tenant_id,
        stream_type="registry",
        stream_id=record.nsrdp_id,
        event_type=f"{record.kind}.amended",
        payload={"changes": changes, "reason": reason},
        actor=actor,
        evidence=evidence or [],
    )
    return record


def get(session: Session, nsrdp_id: str) -> RegistryRecord | None:
    """Lookup within the session's tenant scope."""
    return session.execute(
        select(RegistryRecord).where(RegistryRecord.nsrdp_id == nsrdp_id)
    ).scalar_one_or_none()


def history(session: Session, nsrdp_id: str):
    return read_stream(session, "registry", nsrdp_id)


def _norm(scheme: str, value: Any) -> str:
    v = str(value).strip().upper()
    return v.removeprefix("IMO").strip() if scheme == "imo_number" else v
