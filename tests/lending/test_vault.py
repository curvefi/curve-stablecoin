import boa


def test_vault_creation(vault, market_controller, market_amm, market_mpolicy):
    assert vault.amm() == market_amm.address
    assert vault.controller() == market_controller.address
    assert market_controller.monetary_policy() == market_mpolicy.address


def test_deposit_and_withdraw(vault, borrowed_token, accounts):
    amount = 10**6 * 10 ** borrowed_token.decimals()
    user = accounts[1]
    borrowed_token._mint_for_testing(user, amount)

    with boa.env.prank(user):
        borrowed_token.approve(vault.address, 2**256-1)
        vault.deposit(amount)
        assert vault.totalAssets() == amount
        assert vault.balanceOf(user) == amount
        assert vault.pricePerShare() == 10**18

        vault.redeem(vault.balanceOf(user))
        assert vault.totalAssets() == 0
