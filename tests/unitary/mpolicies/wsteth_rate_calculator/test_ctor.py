"""Tests for WstETHRateCalculator.__init__ (constructor)."""

import boa
import pytest

from tests.unitary.mpolicies.wsteth_rate_calculator.conftest import (
    DAY,
    WINDOW,
    daily_entries,
)
from tests.utils.constants import ZERO_ADDRESS
from tests.utils.deployers import WSTETH_RATE_CALCULATOR_DEPLOYER


def test_immutables_set(oracle, push, deploy_calculator):
    push(oracle, daily_entries(8))
    rate_calc = deploy_calculator(oracle)

    assert rate_calc.wsteth_oracle() == oracle.address
    assert rate_calc.avg_window() == WINDOW


@pytest.mark.parametrize("window", [DAY, 30 * DAY])
def test_window_bounds_inclusive(oracle, push, deploy_calculator, window):
    push(oracle, daily_entries(31))
    assert deploy_calculator(oracle, window).avg_window() == window


def test_zero_oracle_reverts():
    with boa.reverts("Invalid oracle"):
        WSTETH_RATE_CALCULATOR_DEPLOYER.deploy(ZERO_ADDRESS, WINDOW)


@pytest.mark.parametrize(
    "window, error",
    [(DAY - 1, "Window too small"), (30 * DAY + 1, "Window too large")],
)
def test_window_out_of_bounds_reverts(oracle, push, deploy_calculator, window, error):
    push(oracle, daily_entries(31))
    with boa.reverts(error):
        deploy_calculator(oracle, window)


def test_not_enough_history_reverts(oracle, push, deploy_calculator):
    # a 7-day window needs 8 entries: the latest one and the one 7 entries back
    push(oracle, daily_entries(7))
    with boa.reverts("Not enough history"):
        deploy_calculator(oracle)

    push(oracle, daily_entries(1, start_ts=10**10))
    deploy_calculator(oracle)
