"""Tests for rate_write(): access control, EMA update, and the revert fallback."""

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


def test_rate_write_ema_moves_toward_new_rate(
    mp, controller, rate_calculator, default_params
):
    params = ref.get_params(*default_params)
    u = ref.utilization(50 * 10**18, 50 * 10**18, 0)  # controller state -> u = 0.5

    seed = mp.target_rate()
    assert seed == ref.DEFAULT_RATE
    assert mp.rate() == ref.calculate_rate(params, u, seed)

    # Queue a higher rate; at dt=0 rate_write still returns the seed-based rate.
    higher = 3 * ref.DEFAULT_RATE
    rate_calculator.set_rate(higher)
    with boa.env.prank(controller.address):
        result = mp.rate_write()
    # At dt=0 the return still reflects the seed EMA (== rate()).
    assert mp.target_rate() == ref.DEFAULT_RATE
    assert result == mp.rate() == ref.calculate_rate(params, u, ref.DEFAULT_RATE)

    boa.env.time_travel(seconds=20000)  # ~half of TEXP (40000s)

    moved = mp.target_rate()
    assert seed < moved <= higher
    with boa.env.prank(controller.address):
        assert mp.rate_write() == mp.rate() == ref.calculate_rate(params, u, moved)


def test_rate_write_fallback_on_calculator_revert(
    mp, controller, rate_calculator, default_params
):
    params = ref.get_params(*default_params)
    u = ref.utilization(50 * 10**18, 50 * 10**18, 0)

    # A reverting calculator must not brick rate_write; it falls back to 0.
    rate_calculator.set_should_revert(True)

    with boa.env.prank(controller.address):
        result = mp.rate_write()  # should not revert
    # At dt=0 the return still reflects the seed EMA (== rate()).
    assert mp.target_rate() == ref.DEFAULT_RATE
    assert result == mp.rate() == ref.calculate_rate(params, u, ref.DEFAULT_RATE)

    # The 0 got queued; over time the EMA decays toward 0 but is clamped to MIN.
    boa.env.time_travel(seconds=10 * 24 * 3600)

    assert mp.target_rate() == ref.MIN_TARGET_RATE
    with boa.env.prank(controller.address):
        assert (
            mp.rate_write()
            == mp.rate()
            == ref.calculate_rate(params, u, ref.MIN_TARGET_RATE)
        )


def test_rate_write_result_in_ema_bounds(
    mp, controller, rate_calculator, default_params
):
    params = ref.get_params(*default_params)
    u = ref.utilization(50 * 10**18, 50 * 10**18, 0)

    # Even with an out-of-range calculator value, the EMA input is clamped.
    rate_calculator.set_rate(ref.MAX_TARGET_RATE * 100)
    with boa.env.prank(controller.address):
        result = mp.rate_write()
    # At dt=0 the return still reflects the seed EMA (== rate()).
    assert mp.target_rate() == ref.DEFAULT_RATE
    assert result == mp.rate() == ref.calculate_rate(params, u, ref.DEFAULT_RATE)

    boa.env.time_travel(seconds=10 * 24 * 3600)

    assert mp.target_rate() == ref.MAX_TARGET_RATE
    with boa.env.prank(controller.address):
        assert (
            mp.rate_write()
            == mp.rate()
            == ref.calculate_rate(params, u, ref.MAX_TARGET_RATE)
        )
