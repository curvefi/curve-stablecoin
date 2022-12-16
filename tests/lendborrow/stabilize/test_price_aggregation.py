from ...conftest import approx
import boa


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


def test_crypto_agg(dummy_tricrypto, crypto_agg, stableswap_a, stablecoin_a, admin):
    with boa.env.anchor():
        with boa.env.prank(admin):
            assert dummy_tricrypto.price_oracle(0) == 3000 * 10**18
            assert crypto_agg.price() == 3000 * 10**18

            with boa.env.prank(admin):
                crypto_agg.price_w()
                dummy_tricrypto.set_price(0, 1000 * 10**18)
                crypto_agg.price_w()

            assert dummy_tricrypto.price_oracle(0) == 1000 * 10**18
            assert crypto_agg.price() == 3000 * 10**18
            assert crypto_agg.raw_price() == 1000 * 10**18

            boa.env.time_travel(200_000)

            p = crypto_agg.price()
            assert approx(p, 1000 * 10**18, 1e-10)

            amount = 300_000 * 10**6
            stablecoin_a._mint_for_testing(admin, amount)
            stableswap_a.exchange(0, 1, amount, 0)

            boa.env.time_travel(200_000)
            p = stableswap_a.price_oracle()
            assert p > 10**18 * 1.01
            assert crypto_agg.price() > p * 1.01
