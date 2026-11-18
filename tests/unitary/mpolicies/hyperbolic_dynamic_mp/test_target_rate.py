"""Tests for target_rate(): the calculator's base rate, clamped to bounds."""

from tests.utils import hyperbolic_mp_reference as ref


def test_target_rate_in_bounds_passthrough(mp):
    # DEFAULT_RATE is within [MIN, MAX]_TARGET_RATE, so it passes through unclamped.
    assert ref.MIN_TARGET_RATE <= mp.target_rate() <= ref.MAX_TARGET_RATE
    assert mp.target_rate() == ref.DEFAULT_RATE


def test_target_rate_clamped_low(deployer, controller, rate_calculator, default_params):
    # Calculator rate below MIN_TARGET_RATE is clamped up.
    rate_calculator.set_rate(ref.MIN_TARGET_RATE - 1)
    mp = deployer.deploy(
        controller.address, rate_calculator.address, *default_params, 0
    )
    assert mp.target_rate() == ref.MIN_TARGET_RATE


def test_target_rate_clamped_high(
    deployer, controller, rate_calculator, default_params
):
    rate_calculator.set_rate(ref.MAX_TARGET_RATE + 1)
    mp = deployer.deploy(
        controller.address, rate_calculator.address, *default_params, 0
    )
    assert mp.target_rate() == ref.MAX_TARGET_RATE
