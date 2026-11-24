"""Contract tests: every connector has a contract, an owner and a passing contract test (D4).

Stubs always run. A live sandbox runs when NSRDP_SANDBOX_<NAME>=1 and a live adapter is
registered (none exist yet: no interface is confirmed).
"""

import pytest

from nsrdp.connectors.contract import load_all, load_inventory
from nsrdp.connectors.hub import ConnectorHub
from nsrdp.connectors.testing import check_adapter

CONTRACTS = load_all()
INVENTORY = load_inventory()


def test_inventory_has_owner_and_contract_status():
    names = [c["name"] for c in INVENTORY]
    assert len(names) == len(set(names)) == 12
    for entry in INVENTORY:
        assert entry["owner"].strip(), entry
        assert entry["contract"] in {"pending", "not_applicable"} or entry["contract"].endswith(
            ".yaml"
        ), entry


def test_every_contract_file_is_in_inventory():
    listed = {c["contract"] for c in INVENTORY}
    for name in CONTRACTS:
        assert f"{name}.yaml" in listed
    for entry in INVENTORY:
        if entry["contract"].endswith(".yaml"):
            assert entry["contract"].removesuffix(".yaml") in CONTRACTS
            assert CONTRACTS[entry["name"]].owner == entry["owner"]


@pytest.mark.parametrize("name", sorted(CONTRACTS))
def test_stub_honours_contract(name):
    hub = ConnectorHub(CONTRACTS)
    assert check_adapter(CONTRACTS[name], hub.adapter(name)) == []
