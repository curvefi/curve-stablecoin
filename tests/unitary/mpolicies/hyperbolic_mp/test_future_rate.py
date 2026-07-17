"""Tests for future_rate(): the rate under simulated reserve/debt changes.

Asserts bit-exact equality against the Python reference model, exercising
`_get_utilization` with the (_d_reserves, _d_debt) deltas.
"""

import boa
import pytest

from tests.utils import hyperbolic_mp_reference as ref


# (total_debt, available_balance, admin_fees) controller states.
# Utilization u = debt / (available_balance + debt - admin_fees).
STATES = [
    (50 * 10**18, 50 * 10**18, 0),  # u = 0.5
    (10 * 10**18, 90 * 10**18, 0),  # u = 0.1
    (90 * 10**18, 10 * 10**18, 0),  # u = 0.9
    (100 * 10**18, 10 * 10**18, 5 * 10**18),  # with admin fees
    (0, 100 * 10**18, 0),  # u = 0 (no debt)
]


@pytest.mark.parametrize(("debt", "avail", "fees"), STATES)
def test_future_rate_matches_reference(
    mp, controller, default_curve, target_rate, debt, avail, fees
):
    controller.set_state(debt, avail, fees)
    params = ref.get_params(*default_curve)

    d_reserves = 5 * 10**18
    d_debt = 3 * 10**18
    u = ref.utilization(avail, debt, fees, d_reserves, d_debt)
    assert mp.future_rate(d_reserves, d_debt) == ref.calculate_rate(
        params, u, target_rate
    )


def test_future_rate_revert_negative_debt(mp, controller):
    # d_debt drives total_debt below zero -> "Negative debt"
    controller.set_state(10 * 10**18, 90 * 10**18, 0)
    with boa.reverts("Negative debt"):
        mp.future_rate(0, -(11 * 10**18))


def test_future_rate_revert_reserves_too_small(mp, controller):
    # A large negative d_reserves drives total_reserves below total_debt.
    # reserves = 90 + 10 - 0 + d_reserves; with d_reserves = -91e18 -> 9e18 < 10e18 debt.
    controller.set_state(10 * 10**18, 90 * 10**18, 0)
    with boa.reverts("Reserves too small"):
        mp.future_rate(-(91 * 10**18), 0)
