from ....conftest import approx
import boa
import pytest


def test_price_aggregator(stableswap_a, stableswap_b, stablecoin_a, agg, admin):
    amount = 300_000 * 10**6
    dt = 86400

    assert approx(agg.price(), 10**18, 1e-6)
    assert agg.price_pairs(0)[0].lower() == stableswap_a.address.lower()
    assert agg.price_pairs(1)[0].lower() == stableswap_b.address.lower()

    with boa.env.anchor():
        with boa.env.prank(admin):
            stablecoin_a._mint_for_testing(admin, amount)
            stableswap_a.exchange(0, 1, amount, 0)
            p = stableswap_a.get_p()
            assert p > 10**18 * 1.01

            boa.env.time_travel(dt)

            p_o = stableswap_a.price_oracle()
            assert approx(p_o, p, 1e-4)

            # Two coins => agg price is average of the two
            assert approx(agg.price(), (p_o + 10**18) / 2, 1e-3)


@pytest.mark.parametrize(
    "internal_price_1, internal_price_2,external_oracle_price",
    [
        (3000, 1000, 1000),
        (3000, 100, 1000),
        (3000, 10000, 1000),
    ]
)
def test_crypto_agg(
    internal_price_1: int,
    internal_price_2: int,
    external_oracle_price: int,
    dummy_tricrypto,
    crypto_agg,
    stableswap_a,
    stablecoin_a,
    chainlink_price_oracle,
    admin,
):
    def true_raw_price(internal_raw_price, external_oracle_price):
        if external_oracle_price * 0.99 > internal_raw_price:
            return int(external_oracle_price * 0.99)
        elif external_oracle_price * 1.01 < internal_raw_price:
            return int(external_oracle_price * 1.01)
        return internal_raw_price

    with boa.env.anchor():
        with boa.env.prank(admin):
            with boa.env.prank(admin):
                chainlink_price_oracle.set_price(external_oracle_price)

            assert dummy_tricrypto.price_oracle(0) == internal_price_1 * 10 ** 18
            assert crypto_agg.price() == true_raw_price(internal_price_1, external_oracle_price) * 10 ** 18

            with boa.env.prank(admin):
                crypto_agg.price_w()
                dummy_tricrypto.set_price(0, internal_price_2 * 10 ** 18)
                crypto_agg.price_w()

            assert dummy_tricrypto.price_oracle(0) == internal_price_2 * 10 ** 18
            assert crypto_agg.price() == true_raw_price(internal_price_1, external_oracle_price) * 10 ** 18
            assert crypto_agg.raw_price() == true_raw_price(internal_price_2, external_oracle_price) * 10 ** 18

            boa.env.time_travel(200_000)

            p = crypto_agg.price()
            assert approx(p, true_raw_price(internal_price_2, external_oracle_price) * 10 ** 18, 1e-10)

            amount = 300_000 * 10**6
            stablecoin_a._mint_for_testing(admin, amount)
            stableswap_a.exchange(0, 1, amount, 0)

            boa.env.time_travel(200_000)
            p = stableswap_a.price_oracle()
            assert p > 10**18 * 1.01
            assert crypto_agg.price() > p * 1.01
