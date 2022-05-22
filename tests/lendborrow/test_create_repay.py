import brownie
import pytest
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

    h = market_controller.health(user) / 1e18 + 0.02
    assert h >= 0.05 and h <= 0.06

    h = market_controller.health(user, True) / 1e18 + 0.02
    assert approx(h, c_amount * 3000 / l_amount - 1, 0.02)


@pytest.fixture(scope="module", autouse=False)
def existing_loan(collateral_token, market_controller, accounts):
    user = accounts[1]
    c_amount = int(2 * 1e6 * 1e18 * 1.5 / 3000)
    l_amount = 5 * 10**5 * 10**18
    n = 5

    collateral_token._mint_for_testing(user, c_amount, {'from': accounts[0]})
    market_controller.create_loan(c_amount, l_amount, n, {'from': user})


def test_repay_all(stablecoin, collateral_token, market_controller, existing_loan, accounts):
    user = accounts[1]
    c_amount = int(2 * 1e6 * 1e18 * 1.5 / 3000)
    amm = market_controller.amm()
    stablecoin.approve(market_controller, 2**256-1, {'from': user})
    market_controller.repay(2**100, user, {'from': user})
    assert market_controller.debt(user) == 0
    assert stablecoin.balanceOf(user) == 0
    assert collateral_token.balanceOf(user) == c_amount
    assert stablecoin.balanceOf(amm) == 0
    assert collateral_token.balanceOf(amm) == 0
    assert market_controller.total_debt() == 0


def test_repay_half(stablecoin, collateral_token, market_controller, existing_loan, market_amm, accounts):
    user = accounts[1]
    c_amount = int(2 * 1e6 * 1e18 * 1.5 / 3000)
    amm = market_amm
    debt = market_controller.debt(user)
    to_repay = debt // 2

    n_before_0, n_before_1 = market_amm.read_user_tick_numbers(user)
    stablecoin.approve(market_controller, 2**256-1, {'from': user})
    market_controller.repay(to_repay, user, {'from': user})
    n_after_0, n_after_1 = market_amm.read_user_tick_numbers(user)

    assert n_before_1 - n_before_0 == 5
    assert n_after_1 - n_after_0 == 5
    assert n_after_0 > n_before_0

    assert market_controller.debt(user) == debt - to_repay
    assert stablecoin.balanceOf(user) == debt - to_repay
    assert collateral_token.balanceOf(user) == 0
    assert stablecoin.balanceOf(amm) == 0
    assert collateral_token.balanceOf(amm) == c_amount
    assert market_controller.total_debt() == debt - to_repay
