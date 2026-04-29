"""Tests for AggMonetaryPolicy4.remove_peg_keeper"""

import boa

from tests.utils import filter_logs
from tests.utils.constants import ZERO_ADDRESS


def test_default_behavior_removes_keeper_updates_count_and_swaps_tail(
    mp, admin, peg_keepers
):
    """Removing a peg keeper swaps in the last active keeper and shrinks the list."""
    removed = peg_keepers[1]
    replacement = peg_keepers[-1]

    with boa.env.anchor():
        with boa.env.prank(admin):
            mp.remove_peg_keeper(removed.address)

        logs = filter_logs(mp, "RemovePegKeeper")
        assert len(logs) == 1
        assert logs[0].peg_keeper == removed.address

        assert mp.n_peg_keepers() == len(peg_keepers) - 1
        assert mp.peg_keepers(0) == peg_keepers[0].address
        assert mp.peg_keepers(1) == replacement.address
        assert mp.peg_keepers(2) == ZERO_ADDRESS


def test_revert_unauthorized(mp, peg_keepers):
    """Non-admin cannot remove a peg keeper."""
    unauthorized = boa.env.generate_address("unauthorized")

    with boa.env.prank(unauthorized):
        with boa.reverts(dev="only admin"):
            mp.remove_peg_keeper(peg_keepers[0].address)


def test_revert_zero_address(mp, admin):
    """Cannot remove zero address as peg keeper."""
    with boa.env.prank(admin):
        with boa.reverts(dev="peg keeper is zero address"):
            mp.remove_peg_keeper(ZERO_ADDRESS)


def test_revert_nonexistent_address(mp, admin):
    """Cannot remove an address which is not a peg keeper."""
    random_address = boa.env.generate_address("random_address")

    with boa.env.prank(admin):
        with boa.reverts(dev="peg keeper not found"):
            mp.remove_peg_keeper(random_address)
