"""Tests for AggMonetaryPolicy4.debt_ratio_ema_time (view)"""


def test_default_behavior(mp, default_ema_time):
    """Returns the current EMA time value."""
    assert mp.debt_ratio_ema_time() == default_ema_time
