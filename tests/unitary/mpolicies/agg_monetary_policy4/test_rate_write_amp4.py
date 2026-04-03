"""Tests for AggMonetaryPolicy4 rate_write."""

import boa

from tests.utils.constants import ZERO_ADDRESS


def test_revert_zero_address(mp):
    """rate_write rejects the zero address controller key."""
    with boa.reverts(dev="invalid controller"):
        mp.rate_write(ZERO_ADDRESS)
