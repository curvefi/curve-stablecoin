"""Tests for DeltaPPSRateCalculator.__init__ (constructor)."""


def test_vault_immutable_set(rate_calc, vault):
    assert rate_calc.VAULT() == vault.address


def test_buffer_starts_empty(rate_calc, buffer_of):
    assert buffer_of(rate_calc) == [(0, 0)] * 7
