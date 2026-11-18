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


def test_future_rate_deposit_below_admin_fees_pins_utilization(
    mp, controller, default_curve, target_rate
):
    """A deposit smaller than the accrued fees adds no free liquidity.

    admin_fees are netted out of the balance *after* the delta is applied, so
    every deposit up to the fee debt leaves utilization pinned at 100% rather
    than crediting coins that are already owed.
    """
    debt, fees = 1000 * 10**18, 10 * 10**18
    controller.set_state(debt, 0, fees)
    params = ref.get_params(*default_curve)
    at_full = ref.calculate_rate(params, ref.WAD, target_rate)

    for d_reserves in (1, fees // 4, fees // 2, fees - 1, fees):
        assert mp.future_rate(d_reserves, 0) == at_full

    # Past the fee debt the surplus is real liquidity and utilization drops.
    assert mp.future_rate(fees + 5 * 10**18, 0) < at_full


@pytest.mark.parametrize("fees", [0, 10 * 10**18])
def test_future_rate_withdrawal_capped_at_balance_minus_fees(mp, controller, fees):
    """The withdrawal guard mirrors the Controller's transfer-out limit.

    LendController allows at most `sub_or_zero(balance, admin_fees)` to leave, so
    a simulated withdrawal beyond that describes an unreachable state.
    """
    debt, avail = 10 * 10**18, 90 * 10**18
    controller.set_state(debt, avail, fees)
    withdrawable = max(avail - fees, 0)

    mp.future_rate(-withdrawable, 0)  # exactly at the limit is fine
    with boa.reverts("Reserves too small"):
        mp.future_rate(-(withdrawable + 1), 0)
