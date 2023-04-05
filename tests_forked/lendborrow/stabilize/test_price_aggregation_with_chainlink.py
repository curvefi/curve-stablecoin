import pytest


@pytest.mark.parametrize(
    "internal_price_1,internal_price_2",
    [
        (pytest.default_prices[0], 1000 * 10**18),
        (pytest.default_prices[0], 100 * 10**18),
        (pytest.default_prices[0], 10000 * 10**18),
        (pytest.default_prices[0], 0),
    ],
)
def test_crypto_agg(
    internal_price_1: int,
    internal_price_2: int,
    dummy_tricrypto,
    crypto_agg_with_external_oracle,
    stableswap_a,
    stablecoin_a,
    chainlink_aggregator,
    forked_admin,
):
    def true_raw_price(internal_raw_price, external_oracle_price):
        lower, upper = external_oracle_price * 99 // 100, external_oracle_price * 101 // 100
        if lower > internal_raw_price:
            return lower
        elif upper < internal_raw_price:
            return upper
        return internal_raw_price

    external_oracle_price = chainlink_aggregator.latestRoundData()[1] * 10 ** (18 - chainlink_aggregator.decimals())
    if internal_price_2 == 0:
        # test if price IS actually in boundaries
        internal_price_2 = int(external_oracle_price * 995 // 1000)

    assert dummy_tricrypto.price_oracle(0) == internal_price_1
    assert crypto_agg_with_external_oracle.price() == true_raw_price(internal_price_1, external_oracle_price)

    crypto_agg_with_external_oracle.price_w(sender=forked_admin)
    dummy_tricrypto.set_price(0, internal_price_2, sender=forked_admin)
    crypto_agg_with_external_oracle.price_w(sender=forked_admin)

    assert dummy_tricrypto.price_oracle(0) == internal_price_2
    assert crypto_agg_with_external_oracle.price() == true_raw_price(internal_price_1, external_oracle_price)

    assert crypto_agg_with_external_oracle.raw_price() == true_raw_price(internal_price_2, external_oracle_price)
