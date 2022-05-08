import brownie
from ..conftest import approx


def test_create_loan(stablecoin, collateral_token, market_controller, market_amm, monetary_policy, accounts):
    user = accounts[1]
    initial_amount = 10**25
    collateral_token._mint_for_testing(user, initial_amount, {'from': accounts[0]})
    c_amount = int(2 * 1e6 * 1e18 * 1.5 / 3000)

    l_amount = 2 * 10**6 * 10**18
    with brownie.reverts('Debt ceiling'):
        market_controller.create_loan(c_amount, l_amount, 5, {'from': user})

    l_amount = 5 * 10**5 * 10**18
    with brownie.reverts('Need more ticks'):
        market_controller.create_loan(c_amount, l_amount, 4, {'from': user})
    with brownie.reverts('Need less ticks'):
        market_controller.create_loan(c_amount, l_amount, 400, {'from': user})

    with brownie.reverts("Debt too high"):
        market_controller.create_loan(c_amount // 100, l_amount, 5, {'from': user})

    # Phew, the loan finally was created
    market_controller.create_loan(c_amount, l_amount, 5, {'from': user})
    # But cannot do it again
    with brownie.reverts('Loan already created'):
        market_controller.create_loan(c_amount, 1, 5, {'from': user})

    assert stablecoin.balanceOf(user) == l_amount
    assert stablecoin.totalSupply() == l_amount
    assert collateral_token.balanceOf(user) == initial_amount - c_amount

    assert market_controller.total_debt() == l_amount
    assert market_controller.debt(user) == l_amount

    p_up, p_down = market_controller.user_prices(user)
    p_lim = l_amount / c_amount / (1 - market_controller.loan_discount()/1e18)
    assert approx(p_lim, (p_down * p_up)**0.5 / 1e18, 2 / market_amm.A())

    assert market_controller.health(user) == 0
