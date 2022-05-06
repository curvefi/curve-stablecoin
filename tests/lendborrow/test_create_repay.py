import brownie


def test_create_loan(collateral_token, market_controller, market_amm, monetary_policy, accounts):
    user = accounts[1]
    collateral_token._mint_for_testing(user, 10**25, {'from': accounts[0]})
    c_amount = int(2 * 1e6 * 1e18 * 1.5 / 3000)

    l_amount = 2 * 10**6 * 10**18
    with brownie.reverts('Debt ceiling'):
        market_controller.create_loan(c_amount, l_amount, 5, {'from': user})

    l_amount = 5 * 10**6 * 10**18
    with brownie.reverts('Need more ticks'):
        market_controller.create_loan(c_amount, l_amount, 4, {'from': user})
    with brownie.reverts('Need less ticks'):
        market_controller.create_loan(c_amount, l_amount, 400, {'from': user})

    with brownie.reverts("Debt is too high"):
        market_controller.create_loan(c_amount // 100, l_amount, 5, {'from': user})
