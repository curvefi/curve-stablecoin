"""Tests for target_apr(): the annualized fixed base rate."""

from tests.utils import hyperbolic_mp_reference as ref


def test_target_apr_is_annualized_target_rate(mp, target_rate):
    assert mp.target_apr() == target_rate * ref.SECONDS_PER_YEAR


def test_target_apr_tracks_parameter(mp):
    # Annualized directly from the stored target_rate parameter.
    assert mp.target_apr() == mp.parameters().target_rate * ref.SECONDS_PER_YEAR
