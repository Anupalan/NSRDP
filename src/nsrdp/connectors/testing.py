"""Contract-test harness (D4).

``check_adapter`` runs one adapter (stub or live sandbox) against its contract: every
operation is called with the contract's example request and the response must validate.
The same checks run in CI for stubs, and against a sandbox when one is configured.
"""

from __future__ import annotations

from nsrdp.connectors.contract import Contract
from nsrdp.connectors.hub import Adapter
from nsrdp.connectors.stub import example_for


def check_adapter(contract: Contract, adapter: Adapter) -> list[str]:
    """Return a list of failures (empty means the adapter honours the contract)."""
    failures = []
    for name, op in contract.operations.items():
        request = example_for(op.request)
        try:
            contract.check_request(name, request)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}: example request does not satisfy contract: {exc}")
            continue
        try:
            response = adapter.call(name, request, f"contract-test-{name}")
            contract.check_response(name, response)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}: {exc}")
    return failures
