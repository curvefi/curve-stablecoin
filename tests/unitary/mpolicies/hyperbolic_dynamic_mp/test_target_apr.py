"""Tests for target_apr(): the annualized clamped base rate."""

from tests.utils import hyperbolic_mp_reference as ref


def test_target_apr(mp):
    assert mp.target_apr() == ref.DEFAULT_RATE * ref.SECONDS_PER_YEAR


def test_target_apr_tracks_calculator(mp, rate_calculator):
    rate_calculator.set_rate(ref.DEFAULT_RATE + 1)
    assert mp.target_apr() == (ref.DEFAULT_RATE + 1) * ref.SECONDS_PER_YEAR
