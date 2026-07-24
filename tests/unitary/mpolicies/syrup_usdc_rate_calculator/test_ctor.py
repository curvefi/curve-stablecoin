"""Tests for SyrupUSDCRateCalculator.__init__ (constructor)."""


def test_syrup_usdc_immutable_set(rate_calc, syrup):
    assert rate_calc.SYRUP_USDC() == syrup.address


def test_buffer_starts_empty(rate_calc, buffer_of):
    assert buffer_of(rate_calc) == [(0, 0)] * 7
