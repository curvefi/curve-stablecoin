"""Tests for raw_underlying_rate(): the live, unclamped calculator rate."""

from tests.utils import hyperbolic_mp_reference as ref


def test_raw_underlying_rate(mp, rate_calculator):
    assert mp.raw_underlying_rate() == ref.DEFAULT_RATE
    rate_calculator.set_rate(12345)
    # raw view reads the calculator live (no EMA, no clamp)
    assert mp.raw_underlying_rate() == 12345
