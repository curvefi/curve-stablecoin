"""Tests for AggMonetaryPolicy4.set_sigma"""

import boa

from tests.utils import filter_logs

MAX_SIGMA = 10**18
MIN_SIGMA = 10**14


def test_default_behavior(mp, admin):
    """Admin can set new sigma value and SetSigma event is emitted."""
    new_sigma = 3 * 10**16

    with boa.env.prank(admin):
        mp.set_sigma(new_sigma)
        logs = filter_logs(mp, "SetSigma")

    assert mp.sigma() == new_sigma
    assert len(logs) == 1
    assert logs[0].sigma == new_sigma


def test_default_behavior_min_sigma(mp, admin):
    """Can set sigma to MIN_SIGMA."""
    with boa.env.prank(admin):
        mp.set_sigma(MIN_SIGMA)

    assert mp.sigma() == MIN_SIGMA


def test_default_behavior_max_sigma(mp, admin):
    """Can set sigma to MAX_SIGMA."""
    with boa.env.prank(admin):
        mp.set_sigma(MAX_SIGMA)

    assert mp.sigma() == MAX_SIGMA


def test_revert_unauthorized(mp):
    """Non-admin cannot set sigma."""
    unauthorized = boa.env.generate_address("unauthorized")

    with boa.env.prank(unauthorized):
        with boa.reverts(dev="only admin"):
            mp.set_sigma(3 * 10**16)


def test_revert_sigma_too_low(mp, admin):
    """Cannot set sigma below MIN_SIGMA."""
    with boa.env.prank(admin):
        with boa.reverts(dev="sigma too low"):
            mp.set_sigma(MIN_SIGMA - 1)


def test_revert_sigma_too_high(mp, admin):
    """Cannot set sigma above MAX_SIGMA."""
    with boa.env.prank(admin):
        with boa.reverts(dev="sigma too high"):
            mp.set_sigma(MAX_SIGMA + 1)
