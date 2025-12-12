import boa
from tests.utils import filter_logs

NEW_MAX_SUPPLY = 1000000 * 10**18


def test_set_max_supply_by_admin(vault, admin):
    """Test that factory admin can set max supply."""

    # Set max supply as factory admin
    vault.set_max_supply(NEW_MAX_SUPPLY, sender=admin)
    logs = filter_logs(vault, "SetMaxSupply")

    # Verify max supply was updated
    assert vault.maxSupply() == NEW_MAX_SUPPLY

    # Verify log was emitted
    assert len(logs) == 1 and logs[-1].max_supply == NEW_MAX_SUPPLY


def test_set_max_supply_by_factory(vault, proto):
    """Test that factory address can set max supply."""

    # Set max supply as factory
    vault.set_max_supply(NEW_MAX_SUPPLY, sender=proto.lending_factory.address)
    logs = filter_logs(vault, "SetMaxSupply")

    # Verify max supply was updated
    assert vault.maxSupply() == NEW_MAX_SUPPLY

    # Verify log was emitted
    assert len(logs) == 1 and logs[-1].max_supply == NEW_MAX_SUPPLY


def test_set_max_supply_unauthorized_reverts(vault):
    """Test that unauthorized users cannot set max supply."""

    # Attempt to set max supply as unauthorized user
    with boa.reverts():
        vault.set_max_supply(NEW_MAX_SUPPLY)
