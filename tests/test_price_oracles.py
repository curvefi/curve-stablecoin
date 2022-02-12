from .conftest import PRICE


def test_price_oracle(PriceOracle, amm):
    assert PriceOracle.price() == PRICE * 10**18
    assert amm.price_oracle() == PriceOracle.price()
