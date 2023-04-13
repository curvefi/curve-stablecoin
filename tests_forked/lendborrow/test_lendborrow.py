import pytest
from ape import Contract


def test_lend(forked_user, stablecoin_lend, stablecoin):
    assert stablecoin.balanceOf(forked_user) > 0


def test_stableswaps(forked_user, stablecoin_lend, rtokens_pools_with_liquidity, stablecoin):
    for pool in rtokens_pools_with_liquidity:
        n_coins = pool.N_COINS()
        addresses = []
        for n in range(n_coins):
            addr = pool.coins(n)
            addresses.append(addr)

            coin = stablecoin if addr == stablecoin.address else Contract(addr)
            assert pool.balances(n) == pytest.initial_pool_coin_balance * coin.decimals()

        assert stablecoin.address in addresses
