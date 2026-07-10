"""Tests for rate() and the underlying utilization + curve math.

These assert bit-exact equality against the Python reference model, exercising
`_get_utilization` and `_calculate_rate` together through the public view.
"""

import pytest

from tests.utils import hyperbolic_mp_reference as ref


# (total_debt, available_balance, admin_fees) controller states.
# Utilization u = debt / (available_balance + debt - admin_fees).
STATES = [
    (50 * 10**18, 50 * 10**18, 0),    # u = 0.5
    (10 * 10**18, 90 * 10**18, 0),    # u = 0.1
    (90 * 10**18, 10 * 10**18, 0),    # u = 0.9
    (100 * 10**18, 10 * 10**18, 5 * 10**18),  # with admin fees
    (0, 100 * 10**18, 0),             # u = 0 (no debt)
]


@pytest.mark.parametrize(("debt", "avail", "fees"), STATES)
def test_rate_matches_reference(mp, controller, default_params, debt, avail, fees):
    controller.set_state(debt, avail, fees)
    params = ref.get_params(*default_params)
    r0 = mp.target_rate()
    u = ref.utilization(avail, debt, fees)
    assert mp.rate() == ref.calculate_rate(params, u, r0)


def test_rate_zero_debt(mp, controller, default_params):
    controller.set_state(0, 100 * 10**18, 0)
    # At u = 0 the rate reduces to r0*r_minf/1e18 + A*r0/u_inf + shift
    params = ref.get_params(*default_params)
    r0 = mp.target_rate()
    assert mp.rate() == ref.calculate_rate(params, 0, r0)


def test_rate_increases_with_utilization(mp, controller):
    # The curve is monotonically increasing in utilization.
    controller.set_state(10 * 10**18, 90 * 10**18, 0)
    low_u_rate = mp.rate()
    controller.set_state(90 * 10**18, 10 * 10**18, 0)
    high_u_rate = mp.rate()
    assert high_u_rate > low_u_rate


def test_rate_all_reserves_are_fees_zero_reserves(mp, controller):
    # available_balance + total_debt == admin_fees -> total_reserves == 0.
    # With zero debt and zero reserves, utilization is defined as 0 (no revert).
    controller.set_state(0, 10 * 10**18, 10 * 10**18)
    assert mp.rate() >= 0


def test_rate_with_shift(deployer, controller, rate_calculator):
    # A non-zero rate_shift adds a flat term to the curve.
    shift = 5 * 10**9
    params_args = (85 * 10**16, 5 * 10**17, 2 * 10**18, shift)
    mp = deployer.deploy(controller.address, rate_calculator.address, *params_args)
    controller.set_state(50 * 10**18, 50 * 10**18, 0)

    params = ref.get_params(*params_args[:3])
    r0 = mp.target_rate()
    u = ref.utilization(50 * 10**18, 50 * 10**18, 0)
    assert mp.rate() == ref.calculate_rate(params, u, r0, shift)
