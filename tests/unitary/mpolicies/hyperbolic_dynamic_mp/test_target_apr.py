"""Tests for target_apr(): the annualized EMA-smoothed base rate."""

from tests.utils import hyperbolic_mp_reference as ref


def test_target_apr_is_annualized_target_rate(mp):
    assert mp.target_apr() == mp.target_rate() * ref.SECONDS_PER_YEAR


def test_target_apr_at_seed(mp):
    # DEFAULT_RATE is within the EMA bounds, so it is not clamped.
    assert mp.target_apr() == ref.DEFAULT_RATE * ref.SECONDS_PER_YEAR
