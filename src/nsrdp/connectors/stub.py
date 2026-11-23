"""Stub generator: a working simulator built from a contract (D4).

Until an interface is confirmed, code runs against a stub that validates requests and
returns schema-valid responses built from the contract's ``examples``/``enum``/``default``.
Stubs can inject failures to exercise retry and exception handling.
"""

from __future__ import annotations

import copy
from typing import Any

from nsrdp.connectors.contract import Contract


class ConnectorUnavailable(RuntimeError):
    """Transient failure: the call may be retried."""


class ConnectorRejected(RuntimeError):
    """Permanent failure: retrying will not help; route to the owner."""


def example_for(schema: dict[str, Any]) -> Any:
    """Deterministic example value that satisfies ``schema`` (for the subset we use)."""
    for key in ("const",):
        if key in schema:
            return copy.deepcopy(schema[key])
    if schema.get("examples"):
        return copy.deepcopy(schema["examples"][0])
    if "default" in schema:
        return copy.deepcopy(schema["default"])
    if schema.get("enum"):
        return copy.deepcopy(schema["enum"][0])
    t = schema.get("type", "object")
    if isinstance(t, list):
        t = t[0]
    if t == "object":
        props = schema.get("properties", {})
        return {k: example_for(v) for k, v in props.items()}
    if t == "array":
        n = schema.get("minItems", 0)
        return [example_for(schema.get("items", {})) for _ in range(n)]
    if t == "string":
        return "x" * schema.get("minLength", 1)
    if t in ("number", "integer"):
        return schema.get("minimum", 0)
    if t == "boolean":
        return True
    return None


class StubConnector:
    """In-memory simulator for one contract."""

    mode = "stub"

    def __init__(self, contract: Contract):
        self.contract = contract
        self.calls: list[tuple[str, dict[str, Any], str | None]] = []
        self.acknowledged: list[str] = []
        self._fail: dict[str, list[Exception]] = {}
        self._responses: dict[str, Any] = {}

    def fail_next(self, operation: str, *errors: Exception) -> None:
        self._fail.setdefault(operation, []).extend(errors)

    def respond_with(self, operation: str, response: Any) -> None:
        self._responses[operation] = response

    def call(self, operation: str, payload: dict[str, Any], idempotency_key: str | None = None):
        self.calls.append((operation, payload, idempotency_key))
        queue = self._fail.get(operation)
        if queue:
            raise queue.pop(0)
        if operation == self.contract.reconcile_operation:
            return {"keys": list(self.acknowledged)}
        if idempotency_key and idempotency_key not in self.acknowledged:
            self.acknowledged.append(idempotency_key)
        if operation in self._responses:
            return copy.deepcopy(self._responses[operation])
        return example_for(self.contract.operation(operation).response)

    def forget(self, idempotency_key: str) -> None:
        """Simulate the remote side losing a message (for reconciliation tests)."""
        self.acknowledged.remove(idempotency_key)
