"""Tests for AggMonetaryPolicy4.set_rate"""

import boa

from tests.utils import filter_logs

MAX_RATE = 43959106799  # 300% APY


def test_default_behavior(mp, admin):
    """Admin can set new base rate and SetRate event is emitted."""
    new_rate = 1000000000  # ~3.15% APY

    with boa.env.prank(admin):
        mp.set_rate(new_rate)

    logs = filter_logs(mp, "SetRate")

    assert mp.rate0() == new_rate
    assert len(logs) == 1
    assert logs[0].rate == new_rate


def test_default_behavior_max_rate(mp, admin):
    """Can set rate to MAX_RATE."""
    with boa.env.prank(admin):
        mp.set_rate(MAX_RATE)

    assert mp.rate0() == MAX_RATE


def test_revert_unauthorized(mp):
    """Non-admin cannot set rate."""
    unauthorized = boa.env.generate_address("unauthorized")

    with boa.env.prank(unauthorized):
        with boa.reverts(dev="only admin"):
            mp.set_rate(1000000000)


def test_revert_rate_too_high(mp, admin):
    """Cannot set rate above MAX_RATE."""
    with boa.env.prank(admin):
        with boa.reverts(dev="rate too high"):
            mp.set_rate(MAX_RATE + 1)
