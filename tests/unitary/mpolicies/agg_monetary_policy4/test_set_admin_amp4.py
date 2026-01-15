"""Tests for AggMonetaryPolicy4.set_admin"""

import boa

from tests.utils import filter_logs


def test_default_behavior(mp, admin):
    """Admin can transfer admin rights to new address and SetAdmin event is emitted."""
    new_admin = boa.env.generate_address("new_admin")

    with boa.env.prank(admin):
        mp.set_admin(new_admin)
    logs = filter_logs(mp, "SetAdmin")

    assert mp.admin() == new_admin

    # Verify SetAdmin event is emitted with new admin address
    assert len(logs) == 1
    assert logs[0].admin == new_admin


def test_revert_unauthorized(mp):
    """Non-admin cannot call set_admin."""
    unauthorized = boa.env.generate_address("unauthorized")
    new_admin = boa.env.generate_address("new_admin")

    with boa.env.prank(unauthorized):
        with boa.reverts(dev="only admin"):
            mp.set_admin(new_admin)
