"""Connector contracts: one YAML file per external system (D4).

A contract names the connector, its owner and status, and the JSON Schema of each
operation's request and response. Every call through the hub is validated against it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from nsrdp.config import get_settings

_OPERATION = {
    "type": "object",
    "required": ["request", "response"],
    "properties": {
        "idempotent": {"type": "boolean"},
        "request": {"type": "object"},
        "response": {"type": "object"},
    },
}

CONTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["name", "owner", "status", "requirement", "operations"],
    "properties": {
        "name": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
        "inventory_no": {"type": "integer"},
        "requirement": {"type": "string", "minLength": 1},
        "status": {"enum": ["candidate", "agreed", "sandbox", "live", "retired"]},
        "owner": {"type": "string", "minLength": 3},
        "transport": {"type": "string"},
        "operations": {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": _OPERATION,
        },
        "reconcile": {
            "type": "object",
            "required": ["operation"],
            "properties": {"operation": {"type": "string"}},
        },
    },
}


class ContractError(ValueError):
    pass


class ContractViolation(ContractError):
    pass


@dataclass(frozen=True)
class Operation:
    name: str
    request: dict[str, Any]
    response: dict[str, Any]
    idempotent: bool


@dataclass(frozen=True)
class Contract:
    name: str
    owner: str
    status: str
    requirement: str
    operations: dict[str, Operation]
    reconcile_operation: str | None
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Contract:
        try:
            jsonschema.validate(data, CONTRACT_SCHEMA)
        except jsonschema.ValidationError as exc:
            raise ContractError(f"invalid contract: {exc.message}") from exc
        ops: dict[str, Operation] = {}
        for name, spec in data["operations"].items():
            ops[name] = _op(name, spec)
        rec = data.get("reconcile")
        rec_op = None
        if rec:
            rec_op = rec["operation"]
            if rec_op not in rec:
                raise ContractError(f"reconcile operation {rec_op!r} has no schema")
            ops[rec_op] = _op(rec_op, rec[rec_op])
        return cls(
            data["name"], data["owner"], data["status"], data["requirement"], ops, rec_op, data
        )

    @classmethod
    def load(cls, path: Path) -> Contract:
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(yaml.safe_load(fh))

    def operation(self, name: str) -> Operation:
        if name not in self.operations:
            raise ContractViolation(f"{self.name}: no operation {name!r}")
        return self.operations[name]

    def check_request(self, op: str, payload: Any) -> None:
        _check(self.operation(op).request, payload, f"{self.name}.{op} request")

    def check_response(self, op: str, payload: Any) -> None:
        _check(self.operation(op).response, payload, f"{self.name}.{op} response")


def _op(name: str, spec: dict[str, Any]) -> Operation:
    for part in ("request", "response"):
        jsonschema.Draft202012Validator.check_schema(spec[part])
    return Operation(name, spec["request"], spec["response"], bool(spec.get("idempotent")))


def _check(schema: dict[str, Any], payload: Any, what: str) -> None:
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(payload), key=str)
    if errors:
        raise ContractViolation(f"{what}: {errors[0].message}")


def load_all(directory: Path | None = None) -> dict[str, Contract]:
    directory = directory or get_settings().contracts_dir
    out = {}
    for path in sorted(directory.glob("*.yaml")):
        if path.name == "inventory.yaml":
            continue
        c = Contract.load(path)
        if path.stem != c.name:
            raise ContractError(f"{path.name}: file name must match contract name {c.name!r}")
        out[c.name] = c
    return out


def load_inventory(directory: Path | None = None) -> list[dict[str, Any]]:
    directory = directory or get_settings().contracts_dir
    with open(directory / "inventory.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)["connectors"]
