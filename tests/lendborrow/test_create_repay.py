def test_create_loan(collateral_token, market_controller, market_amm, accounts):
    user = accounts[1]
    collateral_token._mint_for_testing(user, 10**25, {'from': accounts[0]})
