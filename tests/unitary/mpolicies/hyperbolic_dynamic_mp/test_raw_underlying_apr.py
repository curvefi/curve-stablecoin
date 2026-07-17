"""Tests for raw_underlying_apr(): the annualized live calculator rate."""

from tests.utils import hyperbolic_mp_reference as ref


def test_raw_underlying_apr(mp):
    assert mp.raw_underlying_apr() == ref.DEFAULT_RATE * ref.SECONDS_PER_YEAR


def test_raw_underlying_apr_tracks_calculator(mp, rate_calculator):
    rate_calculator.set_rate(12345)
    # annualized directly from the live (unclamped) calculator rate
    assert mp.raw_underlying_apr() == 12345 * ref.SECONDS_PER_YEAR
