def test_price_oracle(PriceOracle):
    assert PriceOracle.price() == 3000 * 10**18
