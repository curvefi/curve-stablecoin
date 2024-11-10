import boa


DEAD_SHARES = 1000
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def test_vault_creation(factory_2way, vault_long, vault_short,
                        controller_long, controller_short, amm_long, amm_short,
                        collateral_token, borrowed_token, price_oracle, stablecoin):
    assert controller_long.borrowed_token() == borrowed_token.address
    assert controller_short.borrowed_token() == collateral_token.address
    assert controller_long.collateral_token() == vault_short.address
    assert controller_short.collateral_token() == vault_long.address

    assert amm_long.price_oracle() == price_oracle.price() // DEAD_SHARES
    assert amm_short.price_oracle() == (10**18) ** 2 // DEAD_SHARES // price_oracle.price()
    n = factory_2way.market_count()
    assert n > 0

    assert factory_2way.vaults(n - 2) == vault_long.address
    assert factory_2way.vaults(n - 1) == vault_short.address

    assert factory_2way.amms(n - 2) == vault_long.amm()
    assert factory_2way.amms(n - 1) == vault_short.amm()

    assert factory_2way.controllers(n - 2) == vault_long.controller()
    assert factory_2way.controllers(n - 1) == vault_short.controller()

    assert factory_2way.borrowed_tokens(n - 2) == borrowed_token.address
    assert factory_2way.borrowed_tokens(n - 1) == collateral_token.address

    assert factory_2way.collateral_tokens(n - 2) == vault_short.address
    assert factory_2way.collateral_tokens(n - 1) == vault_long.address

    assert factory_2way.price_oracles(n - 1) != factory_2way.price_oracles(n - 2) != ZERO_ADDRESS

    # Monetary policy is NOT the same - reacts same way on utilization
    assert factory_2way.monetary_policies(n - 1) != factory_2way.monetary_policies(n - 2) != ZERO_ADDRESS

    # Token index
    if borrowed_token == stablecoin:
        token = collateral_token
    else:
        token = borrowed_token
    vaults = set(factory_2way.token_to_vaults(token, i) for i in range(factory_2way.token_market_count(token)))
    assert vault_long.address in vaults
    assert vault_short.address in vaults

    # Vaults index
    assert factory_2way.vaults(factory_2way.vaults_index(vault_long.address)) == vault_long.address
    assert factory_2way.vaults(factory_2way.vaults_index(vault_short.address)) == vault_short.address

    # Gauges
    gauge = factory_2way.deploy_gauge(vault_long.address)
    assert factory_2way.gauge_for_vault(vault_long.address) == gauge
    assert factory_2way.gauges(n - 2) == gauge
    gauge = factory_2way.deploy_gauge(vault_short.address)
    assert factory_2way.gauge_for_vault(vault_short.address) == gauge
    assert factory_2way.gauges(n - 1) == gauge


def test_deposit_and_withdraw(vault_long, vault_short, borrowed_token, collateral_token, accounts):
    one_borrowed_token = 10 ** borrowed_token.decimals()
    one_collateral_token = 10 ** collateral_token.decimals()
    amount_borrowed = 10**6 * one_borrowed_token
    amount_collateral = 10**6 * one_collateral_token // 3000
    user = accounts[1]
    borrowed_token._mint_for_testing(user, amount_borrowed)
    collateral_token._mint_for_testing(user, amount_collateral)

    with boa.env.prank(user):
        borrowed_token.approve(vault_long, 2**256 - 1)
        collateral_token.approve(vault_short, 2**256 - 1)
        vault_long.deposit(amount_borrowed)
        vault_short.deposit(amount_collateral)

        assert vault_long.totalAssets() == amount_borrowed
        assert vault_long.balanceOf(user) == amount_borrowed * 10**18 * DEAD_SHARES // one_borrowed_token
        assert vault_long.pricePerShare() == 10**18 // DEAD_SHARES

        assert vault_short.totalAssets() == amount_collateral
        assert vault_short.balanceOf(user) == amount_collateral * 10**18 * DEAD_SHARES // one_collateral_token
        assert vault_short.pricePerShare() == 10**18 // DEAD_SHARES

        vault_long.redeem(vault_long.balanceOf(user))
        vault_short.redeem(vault_short.balanceOf(user))

        assert vault_long.totalAssets() == 0
        assert vault_short.totalAssets() == 0
