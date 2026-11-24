"""Print simulator payloads for a contract: ``python -m nsrdp.connectors.stubgen esign``.

Gives integrators and partner teams the example request/response pairs the stub serves.
"""

from __future__ import annotations

import json
import sys

from nsrdp.config import get_settings
from nsrdp.connectors.contract import Contract
from nsrdp.connectors.stub import example_for


def render(contract: Contract) -> dict:
    return {
        "connector": contract.name,
        "owner": contract.owner,
        "status": contract.status,
        "operations": {
            name: {"request": example_for(op.request), "response": example_for(op.response)}
            for name, op in contract.operations.items()
        },
    }


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m nsrdp.connectors.stubgen <connector>", file=sys.stderr)
        return 2
    contract = Contract.load(get_settings().contracts_dir / f"{argv[0]}.yaml")
    print(json.dumps(render(contract), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
