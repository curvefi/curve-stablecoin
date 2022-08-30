import pytest
from ...conftest import approx
import boa


@pytest.fixture(scope="module")
def agg(stablecoin, stablecoin_a, stablecoin_b, stableswap_a, stableswap_b, price_aggregator, admin):
    with boa.env.anchor():
        with boa.env.prank(admin):
            stablecoin_a._mint_for_testing(admin, 500000 * 10**6)
            stablecoin_b._mint_for_testing(admin, 500000 * 10**18)

            stablecoin_a.approve(stableswap_a.address, 2**256-1)
            stablecoin.approve(stableswap_a.address, 2**256-1)
            stablecoin_b.approve(stableswap_b.address, 2**256-1)
            stablecoin.approve(stableswap_b.address, 2**256-1)

            stableswap_a.add_liquidity([500000 * 10**6, 500000 * 10**18], 0)
            stableswap_b.add_liquidity([500000 * 10**18, 500000 * 10**18], 0)
        yield price_aggregator


@pytest.fixture(scope="module")
def crypto_agg(dummy_tricrypto, agg, stableswap_a, admin):
    with boa.env.prank(admin):
        crypto_agg = boa.load(
                'contracts/price_oracles/CryptoWithStablePrice.vy',
                dummy_tricrypto.address, 0,
                stableswap_a, agg, 5000)
        crypto_agg.price_w()
        return crypto_agg


def time_travel(dt):
    boa.env.vm.patch.timestamp += dt
    boa.env.vm.patch.block_number += dt // 13 + 1


def test_price_aggregator(stableswap_a, stableswap_b, stablecoin_a, agg, admin):
    amount = 300_000 * 10**6
    dt = 86400

    assert approx(agg.price(), 10**18, 1e-6)
    assert agg.price_pairs(0)[0] == stableswap_a.address
    assert agg.price_pairs(1)[0] == stableswap_b.address

    with boa.env.anchor():
        with boa.env.prank(admin):
            stablecoin_a._mint_for_testing(admin, amount)
            stableswap_a.exchange(0, 1, amount, 0)
            p = stableswap_a.get_p()
            assert p > 10**18 * 1.01

            time_travel(dt)

            p_o = stableswap_a.price_oracle()
            assert approx(p_o, p, 1e-4)

            # Two coins => agg price is average of the two
            assert approx(agg.price(), (p_o + 10**18) / 2, 1e-3)


def test_crypto_agg(dummy_tricrypto, crypto_agg, admin):
    assert dummy_tricrypto.price_oracle(0) == 3000 * 10**18
    assert crypto_agg.price() == 3000 * 10**18

    with boa.env.prank(admin):
        dummy_tricrypto.set_price(0, 1000 * 10**18)
    assert dummy_tricrypto.price_oracle(0) == 1000 * 10**18
    assert crypto_agg.price() == 3000 * 10**18
    assert crypto_agg.raw_price() == 1000 * 10**18

    time_travel(200_000)

    assert approx(crypto_agg.price(), 1000 * 10**18, 1e-10)
