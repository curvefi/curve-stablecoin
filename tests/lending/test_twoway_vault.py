import boa


DEAD_SHARES = 1000


def test_vault_creation(vault_long, vault_short,
                        controller_long, controller_short, amm_long, amm_short,
                        collateral_token, borrowed_token, price_oracle):
    assert controller_long.borrowed_token() == borrowed_token.address
    assert controller_short.borrowed_token() == collateral_token.address
    assert controller_long.collateral_token() == vault_short.address
    assert controller_short.collateral_token() == vault_long.address

    assert amm_long.price_oracle() == price_oracle.price() // DEAD_SHARES
    assert amm_short.price_oracle() == (10**18) ** 2 // DEAD_SHARES // price_oracle.price()


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
