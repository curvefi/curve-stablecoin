import pytest
from tests.amm.conftest import BASE_PRICE


def test_price_oracle(price_oracle, amm):
    assert price_oracle.price() == BASE_PRICE * 10**18
    assert amm.price_oracle() == price_oracle.price()


def test_p_oracle_updown(amm):
    p_base = amm.get_base_price()
    A = amm.A()
    assert amm.p_oracle_up(0) == p_base
    assert amm.p_oracle_down(0) == pytest.approx(p_base * (A - 1) // A, rel=1e-14)

    for i in range(-10, 10):
        mul = ((A - 1) / A) ** i
        p_up = p_base * mul
        p_down = p_up * (A - 1) / A
        assert amm.p_oracle_up(i) == pytest.approx(p_up, rel=1e-14)
        assert amm.p_oracle_down(i) == pytest.approx(p_down, rel=1e-14)


def test_p_current_updown(amm):
    p_base = amm.get_base_price()
    p_oracle = amm.price_oracle()
    A = amm.A()

    for i in range(-1023, 1023):
        mul = ((A - 1) / A) ** i
        p_base_up = p_base * mul
        p_base_down = p_base_up * (A - 1) / A
        p_current_up = p_oracle**3 / p_base_down**2
        p_current_down = p_oracle**3 / p_base_up**2
        assert amm.p_current_up(i) == pytest.approx(p_current_up, rel=1e-10)
        assert amm.p_current_down(i) == pytest.approx(p_current_down, rel=1e-10)
