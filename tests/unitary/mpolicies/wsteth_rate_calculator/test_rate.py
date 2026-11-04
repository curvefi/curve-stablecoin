"""Tests for WstETHRateCalculator.rate() and rate_w().

The rate is the growth of Lido's wstETH/stETH rate between the latest entry and the
one AVG_WINDOW // DAY entries earlier, divided by the time between their L1 reports.
"""

import boa
import pytest

from tests.unitary.mpolicies.wsteth_rate_calculator.conftest import (
    DAY,
    LEGACY_CALCULATOR_DEPLOYER,
    LIDO_OPTIMISM_RATES,
    RATE_PRECISION,
    T0,
    WINDOW,
    daily_entries,
    expected_rate,
)
from tests.utils.deployers import (
    HYPERBOLIC_DYNAMIC_MP_DEPLOYER,
    MOCK_CONTROLLER_MP_DEPLOYER,
)

YEAR = 365 * DAY


def test_rate_matches_reference(oracle, push, deploy_calculator):
    entries = daily_entries(20)
    push(oracle, entries)
    rate_calc = deploy_calculator(oracle)

    assert rate_calc.rate() == expected_rate(entries)
    # 3% APR compounded daily, within rounding of the per-second conversion
    assert abs(rate_calc.rate() * YEAR / 10**18 - 0.03) < 1e-4


def test_rate_w_is_stateless(oracle, push, deploy_calculator):
    push(oracle, daily_entries(20))
    rate_calc = deploy_calculator(oracle)

    assert rate_calc.rate_w() == rate_calc.rate()
    assert rate_calc.rate_w() == rate_calc.rate()


def test_window_is_counted_in_entries(oracle, push, deploy_calculator):
    # entries arrive at uneven times; the window steps back 7 entries, not 7 days
    entries = [
        (RATE_PRECISION + i * 10**23, T0 + i * DAY + (i % 3) * 3600) for i in range(12)
    ]
    push(oracle, entries)

    assert deploy_calculator(oracle).rate() == expected_rate(entries)


def test_window_rounds_down_to_whole_days(oracle, push, deploy_calculator):
    entries = daily_entries(20)
    push(oracle, entries)

    rate_calc = deploy_calculator(oracle, 7 * DAY + DAY // 2)
    assert rate_calc.rate() == expected_rate(entries, 7 * DAY)


def test_uses_l1_report_timestamp(oracle, push, deploy_calculator):
    # the mock's rateReceivedL2Timestamp lags entry 0 by 1h and entry 7 by 2h, so the
    # rate would come out different if that field were used
    entries = [(RATE_PRECISION + i * 10**23, T0 + i * DAY) for i in range(8)]
    push(oracle, entries)

    assert deploy_calculator(oracle).rate() == expected_rate(entries)


@pytest.mark.parametrize(
    "latest",
    [
        pytest.param((12 * RATE_PRECISION // 10, T0 + 7 * DAY), id="flat"),
        pytest.param((11 * RATE_PRECISION // 10, T0 + 7 * DAY), id="falling"),
        pytest.param((13 * RATE_PRECISION // 10, T0), id="same-timestamp"),
    ],
)
def test_returns_zero_without_growth(oracle, push, deploy_calculator, latest):
    push(oracle, [(12 * RATE_PRECISION // 10, T0)] * 7 + [latest])

    rate_calc = deploy_calculator(oracle)
    assert rate_calc.rate() == 0
    assert rate_calc.rate_w() == 0


def test_returns_zero_when_history_shrinks(oracle, push, deploy_calculator):
    # deployment checks the history, but an oracle upgrade could reset it
    push(oracle, daily_entries(8))
    rate_calc = deploy_calculator(oracle)
    assert rate_calc.rate() > 0

    oracle.pop()
    assert rate_calc.rate() == 0
    assert rate_calc.rate_w() == 0


@pytest.mark.parametrize("window", [1 * DAY, 7 * DAY, 14 * DAY])
def test_lido_optimism_data(oracle, push, deploy_calculator, window):
    push(oracle, LIDO_OPTIMISM_RATES)
    rate = deploy_calculator(oracle, window).rate()

    assert rate == expected_rate(LIDO_OPTIMISM_RATES, window)
    # wstETH staking yield around 2.2% APR in October 2026
    assert 0.02 < rate * YEAR / 10**18 < 0.025


@pytest.mark.parametrize(
    "entries",
    [
        pytest.param(LIDO_OPTIMISM_RATES, id="lido-optimism"),
        pytest.param(daily_entries(20), id="synthetic"),
        pytest.param(
            [(10**27 + i * 10**23, T0 + i * DAY + (i % 3) * 3600) for i in range(12)],
            id="uneven",
        ),
    ],
)
def test_matches_legacy_calculator(oracle, push, deploy_calculator, entries):
    # the calculator it replaces, with the 7-day window it is deployed with
    push(oracle, entries)
    legacy = LEGACY_CALCULATOR_DEPLOYER.deploy(
        oracle.address, boa.env.generate_address(), WINDOW
    )

    assert deploy_calculator(oracle).rate() == legacy.rate()


def test_drives_hyperbolic_dynamic_mp(oracle, push, deploy_calculator):
    push(oracle, LIDO_OPTIMISM_RATES)
    rate_calc = deploy_calculator(oracle)
    controller = MOCK_CONTROLLER_MP_DEPLOYER.deploy(boa.env.generate_address())
    mp = HYPERBOLIC_DYNAMIC_MP_DEPLOYER.deploy(
        controller.address, rate_calc.address, 85 * 10**16, 5 * 10**17, 3 * 10**18, 0
    )

    assert mp.target_rate() == rate_calc.rate()
    with boa.env.prank(controller.address):
        mp.rate_write()
