from .conftest import PRICE


def test_price_oracle(PriceOracle, amm):
    assert PriceOracle.price() == PRICE * 10**18
    assert amm.price_oracle() == PriceOracle.price()
    addr, sig = amm.price_oracle_signature()
    assert addr == PriceOracle.address
    assert sig == PriceOracle.price.signature
