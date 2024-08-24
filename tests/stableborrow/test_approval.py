import boa
import pytest


@pytest.fixture(scope="module")
def existing_loan(collateral_token, market_controller, accounts):
    user = accounts[0]
    c_amount = int(2 * 1e6 * 1e18 * 1.5 / 3000)
    l_amount = 5 * 10**5 * 10**18
    n = 5

    with boa.env.prank(user):
        collateral_token._mint_for_testing(user, c_amount)
        market_controller.create_loan(c_amount, l_amount, n)


def test_create_loan(controller_factory, stablecoin, collateral_token, market_controller, market_amm, monetary_policy, accounts):
    user = accounts[0]
    someone_else = accounts[1]

    initial_amount = 10**25
    c_amount = int(2 * 1e6 * 1e18 * 1.5 / 3000)
    l_amount = 5 * 10**5 * 10**18

    with boa.env.prank(user):
        with boa.env.anchor():
            collateral_token._mint_for_testing(user, initial_amount)
            market_controller.create_loan(c_amount, l_amount, 5)

    collateral_token._mint_for_testing(someone_else, initial_amount)

    with boa.env.anchor():
        with boa.env.prank(someone_else):
            with boa.reverts():
                market_controller.create_loan(c_amount, l_amount, 5, user)
        with boa.env.prank(user):
            market_controller.approve(someone_else, False)
        with boa.env.prank(someone_else):
            with boa.reverts():
                market_controller.create_loan(c_amount, l_amount, 5, user)
        with boa.env.prank(user):
            market_controller.approve(someone_else, True)
        with boa.env.prank(someone_else):
            market_controller.create_loan(c_amount, l_amount, 5, user)


def test_repay_all(stablecoin, collateral_token, market_controller, existing_loan, accounts):
    user = accounts[0]
    someone_else = accounts[1]
    c_amount = int(2 * 1e6 * 1e18 * 1.5 / 3000)
    amm = market_controller.amm()

    with boa.env.prank(user):
        stablecoin.transfer(someone_else, stablecoin.balanceOf(user))

    with boa.env.prank(user):
        market_controller.approve(someone_else, True)

    # In this particular case, it could have been easily removed without approval, too
    # because health is still good and loan is not underwater

    with boa.env.prank(someone_else):
        stablecoin.approve(market_controller, 2**256-1)
        market_controller.repay(2**100, user)
        assert market_controller.debt(user) == 0
        assert stablecoin.balanceOf(user) == 0
        assert collateral_token.balanceOf(user) == c_amount
        assert stablecoin.balanceOf(amm) == 0
        assert collateral_token.balanceOf(amm) == 0
        assert market_controller.total_debt() == 0


def test_borrow_more(stablecoin, collateral_token, market_controller, existing_loan, market_amm, accounts):
    user = accounts[0]
    someone_else = accounts[1]

    debt = market_controller.debt(user)
    more_debt = debt // 10
    c_amount = int(2 * 1e6 * 1e18 * 1.5 / 3000)

    n_before_0, n_before_1 = market_amm.read_user_tick_numbers(user)

    with boa.env.prank(someone_else):
        with boa.reverts():
            market_controller.borrow_more(0, more_debt, user)

    with boa.env.prank(user):
        market_controller.approve(someone_else, True)

    with boa.env.prank(someone_else):
        market_controller.borrow_more(0, more_debt, user)
        n_after_0, n_after_1 = market_amm.read_user_tick_numbers(user)

        assert n_before_1 - n_before_0 + 1 == 5
        assert n_after_1 - n_after_0 + 1 == 5
        assert n_after_0 < n_before_0

        assert market_controller.debt(user) == debt + more_debt
        assert stablecoin.balanceOf(user) == debt + more_debt
        assert collateral_token.balanceOf(user) == 0
        assert stablecoin.balanceOf(market_amm) == 0
        assert collateral_token.balanceOf(market_amm) == c_amount
        assert market_controller.total_debt() == debt + more_debt


def test_remove_collateral(stablecoin, collateral_token, market_controller, existing_loan, market_amm, accounts):
    user = accounts[0]
    someone_else = accounts[1]

    debt = market_controller.debt(user)
    c_amount = int(2 * 1e6 * 1e18 * 1.5 / 3000)

    with boa.env.prank(someone_else):
        with boa.reverts():
            market_controller.remove_collateral(c_amount // 10, user)

    with boa.env.prank(user):
        market_controller.approve(someone_else, True)

    with boa.env.prank(someone_else):
        market_controller.remove_collateral(c_amount // 10, user)

        assert market_controller.debt(user) == debt
        assert stablecoin.balanceOf(user) == debt
        assert collateral_token.balanceOf(user) == c_amount // 10
        assert stablecoin.balanceOf(market_amm) == 0
        assert collateral_token.balanceOf(market_amm) == c_amount - c_amount // 10
        assert market_controller.total_debt() == debt
