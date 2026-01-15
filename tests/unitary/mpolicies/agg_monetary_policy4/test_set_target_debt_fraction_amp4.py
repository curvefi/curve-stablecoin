"""Tests for AggMonetaryPolicy4.set_target_debt_fraction"""

import boa

from tests.utils import filter_logs

MAX_TARGET_DEBT_FRACTION = 10**18


def test_default_behavior(mp, admin):
    """Admin can set new target debt fraction and SetTargetDebtFraction event is emitted."""
    new_fraction = 2 * 10**17  # 20%

    with boa.env.prank(admin):
        mp.set_target_debt_fraction(new_fraction)
    
    logs = filter_logs(mp, "SetTargetDebtFraction")

    assert mp.target_debt_fraction() == new_fraction
    assert len(logs) == 1
    assert logs[0].target_debt_fraction == new_fraction


def test_default_behavior_max_fraction(mp, admin):
    """Can set target debt fraction to MAX_TARGET_DEBT_FRACTION."""
    with boa.env.prank(admin):
        mp.set_target_debt_fraction(MAX_TARGET_DEBT_FRACTION)

    assert mp.target_debt_fraction() == MAX_TARGET_DEBT_FRACTION


def test_revert_unauthorized(mp):
    """Non-admin cannot set target debt fraction."""
    unauthorized = boa.env.generate_address("unauthorized")

    with boa.env.prank(unauthorized):
        with boa.reverts(dev="only admin"):
            mp.set_target_debt_fraction(2 * 10**17)


def test_revert_zero(mp, admin):
    """Cannot set target debt fraction to zero."""
    with boa.env.prank(admin):
        with boa.reverts(dev="target debt fraction is zero"):
            mp.set_target_debt_fraction(0)


def test_revert_too_high(mp, admin):
    """Cannot set target debt fraction above MAX_TARGET_DEBT_FRACTION."""
    with boa.env.prank(admin):
        with boa.reverts(dev="target debt fraction too high"):
            mp.set_target_debt_fraction(MAX_TARGET_DEBT_FRACTION + 1)
