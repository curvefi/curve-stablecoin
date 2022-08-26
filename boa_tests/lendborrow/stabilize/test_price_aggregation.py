import boa


def test_price_aggregator(stablecoin, stablecoin_a, stablecoin_b, stableswap_a, stableswap_b, price_aggregator, admin):
    with boa.env.prank(admin):
        stablecoin_a._mint_for_testing(admin, 500000 * 10**6)
        stablecoin_b._mint_for_testing(admin, 500000 * 10**18)

        stablecoin_a.approve(stableswap_a.address, 2**256-1)
        stablecoin.approve(stableswap_a.address, 2**256-1)
        stablecoin_b.approve(stableswap_b.address, 2**256-1)
        stablecoin.approve(stableswap_b.address, 2**256-1)

        stableswap_a.add_liquidity([500000 * 10**6, 500000 * 10**18], 0)
        stableswap_b.add_liquidity([500000 * 10**18, 500000 * 10**18], 0)
