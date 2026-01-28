"""Tests for AggMonetaryPolicy4.set_extra_const"""

import boa

from tests.utils import filter_logs

MAX_EXTRA_CONST = 43959106799  # MAX_RATE


def test_default_behavior(mp, admin):
    """Admin can set new extra constant and SetExtraConst event is emitted."""
    new_const = 100000000

    with boa.env.prank(admin):
        mp.set_extra_const(new_const)
    logs = filter_logs(mp, "SetExtraConst")

    assert mp.extra_const() == new_const
    assert len(logs) == 1
    assert logs[0].extra_const == new_const


def test_default_behavior_max_const(mp, admin):
    """Can set extra const to MAX_EXTRA_CONST."""
    with boa.env.prank(admin):
        mp.set_extra_const(MAX_EXTRA_CONST)

    assert mp.extra_const() == MAX_EXTRA_CONST


def test_default_behavior_zero(mp, admin):
    """Can set extra const to zero."""
    # First set to non-zero
    with boa.env.prank(admin):
        mp.set_extra_const(100000000)

    # Then set back to zero
    with boa.env.prank(admin):
        mp.set_extra_const(0)

    assert mp.extra_const() == 0


def test_revert_unauthorized(mp):
    """Non-admin cannot set extra const."""
    unauthorized = boa.env.generate_address("unauthorized")

    with boa.env.prank(unauthorized):
        with boa.reverts(dev="only admin"):
            mp.set_extra_const(100000000)


def test_revert_too_high(mp, admin):
    """Cannot set extra const above MAX_EXTRA_CONST."""
    with boa.env.prank(admin):
        with boa.reverts(dev="extra const too high"):
            mp.set_extra_const(MAX_EXTRA_CONST + 1)
