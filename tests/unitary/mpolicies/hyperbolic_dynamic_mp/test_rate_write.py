"""Tests for rate_write(): access control, calculator read, and the revert fallback."""

import pytest
import boa

from tests.utils import hyperbolic_mp_reference as ref
from tests.utils.deployers import MOCK_CONTROLLER_MP_DEPLOYER


@pytest.fixture
def controller(factory):
    """Fresh mock controller returning `factory` as its factory."""
    _controller = MOCK_CONTROLLER_MP_DEPLOYER.deploy(factory.address)
    _controller.set_state(50 * 10**18, 50 * 10**18, 0)
    return _controller


def test_rate_write_only_controller(mp):
    stranger = boa.env.generate_address("stranger")
    with boa.env.prank(stranger):
        with boa.reverts("Controller only"):
            mp.rate_write()


def test_rate_write_matches_rate_at_seed(mp, controller, default_params):
    params = ref.get_params(*default_params)
    u = ref.utilization(
        controller.available_balance(), controller.total_debt(), 0
    )  # controller state -> u = 0.5
    with boa.env.prank(controller.address):
        assert (
            mp.rate_write()
            == mp.rate()
            == ref.calculate_rate(params, u, ref.DEFAULT_RATE)
        )


def test_rate_write_tracks_new_target_rate(mp, controller, rate_calculator, default_params):
    params = ref.get_params(*default_params)
    u = ref.utilization(50 * 10**18, 50 * 10**18, 0)  # controller state -> u = 0.5

    assert mp.rate() == ref.calculate_rate(params, u, ref.DEFAULT_RATE)

    # A new calculator rate is reflected immediately
    higher = 3 * ref.DEFAULT_RATE
    rate_calculator.set_rate(higher)
    with boa.env.prank(controller.address):
        result = mp.rate_write()

    assert mp.target_rate() == higher
    assert result == mp.rate() == ref.calculate_rate(params, u, higher)


def test_rate_write_fallback_on_calculator_revert(
    mp, controller, rate_calculator, default_params
):
    params = ref.get_params(*default_params)
    u = ref.utilization(50 * 10**18, 50 * 10**18, 0)

    # A reverting calculator must not brick rate_write or the views; the rate
    # falls back to 0, which is then clamped up to MIN_TARGET_RATE.
    rate_calculator.set_should_revert(True)

    with boa.env.prank(controller.address):
        result = mp.rate_write()  # must not revert
    assert result == ref.calculate_rate(params, u, ref.MIN_TARGET_RATE)

    # The read-only views share the fallback: they return the clamped MIN, not revert.
    assert mp.target_rate() == ref.MIN_TARGET_RATE
    assert mp.rate() == ref.calculate_rate(params, u, ref.MIN_TARGET_RATE)


def test_rate_write_result_clamped_low(
    mp, controller, rate_calculator, default_params
):
    params = ref.get_params(*default_params)
    u = ref.utilization(50 * 10**18, 50 * 10**18, 0)

    # An out-of-range calculator value is clamped down to MIN_TARGET_RATE.
    rate_calculator.set_rate(ref.MIN_TARGET_RATE // 2)
    with boa.env.prank(controller.address):
        result = mp.rate_write()

    assert mp.target_rate() == ref.MIN_TARGET_RATE
    assert result == mp.rate() == ref.calculate_rate(params, u, ref.MIN_TARGET_RATE)


def test_rate_write_result_clamped_high(
    mp, controller, rate_calculator, default_params
):
    params = ref.get_params(*default_params)
    u = ref.utilization(50 * 10**18, 50 * 10**18, 0)

    # An out-of-range calculator value is clamped down to MAX_TARGET_RATE.
    rate_calculator.set_rate(ref.MAX_TARGET_RATE * 100)
    with boa.env.prank(controller.address):
        result = mp.rate_write()

    assert mp.target_rate() == ref.MAX_TARGET_RATE
    assert result == mp.rate() == ref.calculate_rate(params, u, ref.MAX_TARGET_RATE)
