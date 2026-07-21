"""Tests for SyrupUSDCRateCalculator.rate_w().

Covers the ring-buffer recording logic, the once-per-day gate, and the
per-second rate arithmetic, plus a full replay against recorded mainnet PPS
samples (see tests/utils/syrup_pps_data.py).
"""

import pytest

from tests.unitary.mpolicies.syrup_usdc_rate_calculator.conftest import DAY, WAD
from tests.unitary.mpolicies.syrup_usdc_rate_calculator.test_syrup_pps_data import (
    SYRUP_PPS_DAYS,
)

T0 = 1_700_000_000  # arbitrary start timestamp for synthetic scenarios


# --------------------------------------------------------------------------- #
#                              First record                                   #
# --------------------------------------------------------------------------- #


def test_first_call_records_slot0_and_returns_zero(rate_calc, syrup, step, buffer_of):
    pps = 12 * WAD // 10
    rate = step(rate_calc, syrup, T0, pps)

    assert rate == 0  # need at least two records for a rate
    assert buffer_of(rate_calc) == [(pps, T0)] + [(0, 0)] * 6


def test_second_call_same_day_is_noop(rate_calc, syrup, step, buffer_of):
    pps = 12 * WAD // 10
    step(rate_calc, syrup, T0, pps)

    # A day has not passed: no new record, still a single record -> rate 0.
    rate = step(rate_calc, syrup, T0 + DAY - 1, pps + 10**15)
    assert rate == 0
    assert buffer_of(rate_calc) == [(pps, T0)] + [(0, 0)] * 6


# --------------------------------------------------------------------------- #
#                          Once-per-day gate                                  #
# --------------------------------------------------------------------------- #


def test_append_triggers_exactly_at_day_boundary(rate_calc, syrup, step, buffer_of):
    pps0 = WAD
    pps1 = WAD + 10**16
    step(rate_calc, syrup, T0, pps0)

    # Exactly DAY later is "due" (>=), so a second record is appended.
    step(rate_calc, syrup, T0 + DAY, pps1)
    assert buffer_of(rate_calc)[:2] == [(pps0, T0), (pps1, T0 + DAY)]


def test_no_append_just_under_a_day(rate_calc, syrup, step, buffer_of):
    pps0 = WAD
    step(rate_calc, syrup, T0, pps0)

    # One second short of a day: not due, buffer unchanged.
    step(rate_calc, syrup, T0 + DAY - 1, pps0 + 10**16)
    assert buffer_of(rate_calc) == [(pps0, T0)] + [(0, 0)] * 6


def test_at_most_one_record_per_day(rate_calc, syrup, step, buffer_of):
    pps0, pps1 = WAD, WAD + 10**16
    step(rate_calc, syrup, T0, pps0)
    step(rate_calc, syrup, T0 + DAY, pps1)

    # A further call the same (second) day must not append a third record.
    step(rate_calc, syrup, T0 + DAY + 100, pps1 + 10**16)
    assert buffer_of(rate_calc) == [(pps0, T0), (pps1, T0 + DAY)] + [(0, 0)] * 5


# --------------------------------------------------------------------------- #
#                           Rate arithmetic                                   #
# --------------------------------------------------------------------------- #


def test_rate_matches_manual_growth_formula(rate_calc, syrup, step):
    pps0 = WAD
    pps1 = WAD + WAD // 100  # +1% over one day
    step(rate_calc, syrup, T0, pps0)
    rate = step(rate_calc, syrup, T0 + DAY, pps1)

    growth = (pps1 - pps0) * WAD // pps0
    assert rate == growth // DAY
    assert rate > 0


def test_flat_pps_returns_zero(rate_calc, syrup, step, buffer_of):
    pps = 15 * WAD // 10
    step(rate_calc, syrup, T0, pps)
    rate = step(rate_calc, syrup, T0 + DAY, pps)  # no growth

    assert rate == 0
    # The record is still appended even though the rate is zero.
    assert buffer_of(rate_calc)[:2] == [(pps, T0), (pps, T0 + DAY)]


def test_decreasing_pps_returns_zero(rate_calc, syrup, step, buffer_of):
    pps0 = 15 * WAD // 10
    pps1 = pps0 - 10**16
    step(rate_calc, syrup, T0, pps0)
    rate = step(rate_calc, syrup, T0 + DAY, pps1)

    assert rate == 0
    assert buffer_of(rate_calc)[:2] == [(pps0, T0), (pps1, T0 + DAY)]


# --------------------------------------------------------------------------- #
#                       Ring buffer wrap-around                               #
# --------------------------------------------------------------------------- #


def test_ring_buffer_wraps_after_seven_records(rate_calc, syrup, step, buffer_of):
    # Fill all 7 slots on days 0..6.
    pps_by_day = [WAD + i * 10**16 for i in range(8)]
    for d in range(7):
        step(rate_calc, syrup, T0 + d * DAY, pps_by_day[d])

    assert buffer_of(rate_calc) == [(pps_by_day[d], T0 + d * DAY) for d in range(7)]

    # Day 7 wraps and overwrites slot 0; the window then spans slots 1..0.
    step(rate_calc, syrup, T0 + 7 * DAY, pps_by_day[7])
    buf = buffer_of(rate_calc)
    assert buf[0] == (pps_by_day[7], T0 + 7 * DAY)
    assert buf[1:] == [(pps_by_day[d], T0 + d * DAY) for d in range(1, 7)]


def test_rate_uses_seven_day_window_after_fill(rate_calc, syrup, step):
    # After the buffer is full, the rate spans oldest (slot after newest) to
    # newest, i.e. a ~6-day span for a fully wrapped buffer.
    pps_by_day = [WAD + i * 10**16 for i in range(8)]
    for d in range(7):
        step(rate_calc, syrup, T0 + d * DAY, pps_by_day[d])

    rate = step(rate_calc, syrup, T0 + 7 * DAY, pps_by_day[7])

    # newest = slot0 (day7), oldest = slot1 (day1): span of 6 days.
    newest_pps, newest_ts = pps_by_day[7], T0 + 7 * DAY
    oldest_pps, oldest_ts = pps_by_day[1], T0 + 1 * DAY
    growth = (newest_pps - oldest_pps) * WAD // oldest_pps
    assert rate == growth // (newest_ts - oldest_ts)


# --------------------------------------------------------------------------- #
#                    Full replay against recorded mainnet data                #
# --------------------------------------------------------------------------- #


def test_replay_recorded_mainnet_samples(rate_calc, syrup, step, buffer_of):
    """Feed ~30 days of recorded syrupUSDC PPS and assert the calculator
    reproduces both the returned rate and the ring-buffer state at every step."""
    for i, day in enumerate(SYRUP_PPS_DAYS):
        rate = step(rate_calc, syrup, day["ts"], day["pps"])
        assert rate == day["rate"], f"rate mismatch on day {i}"
        assert buffer_of(rate_calc) == day["after"], f"buffer mismatch on day {i}"
