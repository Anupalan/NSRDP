"""The integration hub: the only way to call an external system (D4).

Channels and domain modules never call external systems directly. They call
``hub.call(connector, operation, payload)`` for synchronous lookups, or enqueue an outbox
message for anything that must not be lost (see :mod:`nsrdp.connectors.outbox`).
Both requests and responses are validated against the connector's contract.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

from nsrdp.config import load_policy
from nsrdp.connectors.contract import Contract, load_all
from nsrdp.connectors.stub import StubConnector


class Adapter(Protocol):
    mode: str

    def call(
        self, operation: str, payload: dict[str, Any], idempotency_key: str | None = None
    ) -> Any: ...


class HubConfigError(RuntimeError):
    pass


class ConnectorHub:
    def __init__(self, contracts: dict[str, Contract], policy: dict[str, Any] | None = None):
        self.contracts = contracts
        self.policy = policy if policy is not None else load_policy("connectors")
        self.adapters: dict[str, Adapter] = {}
        for name, contract in contracts.items():
            mode = self._mode(name)
            if mode == "stub":
                self.adapters[name] = StubConnector(contract)
            elif mode != "live":
                raise HubConfigError(f"{name}: unknown mode {mode!r}")
            # live adapters are registered explicitly with register_live()

    @classmethod
    def from_contracts_dir(cls) -> ConnectorHub:
        return cls(load_all())

    def _mode(self, name: str) -> str:
        env = os.environ.get(f"NSRDP_CONNECTOR_{name.upper()}_MODE")
        return env or (self.policy.get("modes") or {}).get(name, "stub")

    def register_live(self, name: str, adapter: Adapter) -> None:
        if name not in self.contracts:
            raise HubConfigError(f"no contract for {name!r}; every connector needs one")
        self.adapters[name] = adapter

    def adapter(self, name: str) -> Adapter:
        if name not in self.adapters:
            raise HubConfigError(f"connector {name!r} is not available (no contract or adapter)")
        return self.adapters[name]

    def retry_policy(self, name: str) -> dict[str, Any]:
        p = dict(self.policy["defaults"])
        p.update((self.policy.get("overrides") or {}).get(name, {}))
        return p

    def owner(self, name: str) -> str:
        return self.contracts[name].owner

    def call(
        self,
        connector: str,
        operation: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> Any:
        contract = self.contracts.get(connector)
        if contract is None:
            raise HubConfigError(f"no contract for {connector!r}")
        contract.check_request(operation, payload)
        response = self.adapter(connector).call(operation, payload, idempotency_key)
        contract.check_response(operation, response)
        return response
