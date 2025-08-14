import boa
import pytest
from hypothesis import given
from hypothesis import strategies as st
from ..conftest import approx


def test_create_loan(controller_factory, stablecoin, collateral_token, market_controller, market_amm, monetary_policy, accounts):
    user = accounts[0]
    with boa.env.anchor():
        with boa.env.prank(user):
            initial_amount = 10**25
            boa.deal(collateral_token, user, initial_amount)
            c_amount = int(2 * 1e6 * 1e18 * 1.5 / 3000)

            l_amount = 2 * 10**6 * 10**18
            with boa.reverts():
                market_controller.create_loan(c_amount, l_amount, 5)

            l_amount = 5 * 10**5 * 10**18
            with boa.reverts('Need more ticks'):
                market_controller.create_loan(c_amount, l_amount, 3)
            with boa.reverts('Need less ticks'):
                market_controller.create_loan(c_amount, l_amount, 400)

            with boa.reverts("Debt too high"):
                market_controller.create_loan(c_amount // 100, l_amount, 5)

            # Phew, the loan finally was created
            market_controller.create_loan(c_amount, l_amount, 5)
            # But cannot do it again
            with boa.reverts('Loan already created'):
                market_controller.create_loan(c_amount, 1, 5)

            assert stablecoin.balanceOf(user) == l_amount
            assert l_amount == stablecoin.totalSupply() - stablecoin.balanceOf(market_controller)
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


@given(
    collateral_amount=st.integers(min_value=10**9, max_value=10**20),
    n=st.integers(min_value=5, max_value=50),
)
def test_max_borrowable(market_controller, accounts, collateral_amount, n):
    max_borrowable = market_controller.max_borrowable(collateral_amount, n)
    with boa.reverts('Debt too high'):
        market_controller.calculate_debt_n1(collateral_amount, int(max_borrowable * 1.001), n)
    market_controller.calculate_debt_n1(collateral_amount, max_borrowable, n)


@pytest.fixture(scope="module")
def existing_loan(collateral_token, market_controller, accounts):
    user = accounts[0]
    c_amount = int(2 * 1e6 * 1e18 * 1.5 / 3000)
    l_amount = 5 * 10**5 * 10**18
    n = 5

    with boa.env.prank(user):
        boa.deal(collateral_token, user, c_amount)
        market_controller.create_loan(c_amount, l_amount, n)


def test_repay_all(stablecoin, collateral_token, market_controller, existing_loan, accounts):
    user = accounts[0]
    with boa.env.anchor():
        with boa.env.prank(user):
            c_amount = int(2 * 1e6 * 1e18 * 1.5 / 3000)
            amm = market_controller.amm()
            stablecoin.approve(market_controller, 2**256-1)
            market_controller.repay(2**100, user)
            assert market_controller.debt(user) == 0
            assert stablecoin.balanceOf(user) == 0
            assert collateral_token.balanceOf(user) == c_amount
            assert stablecoin.balanceOf(amm) == 0
            assert collateral_token.balanceOf(amm) == 0
            assert market_controller.total_debt() == 0


def test_repay_half(stablecoin, collateral_token, market_controller, existing_loan, market_amm, accounts):
    user = accounts[0]

    with boa.env.anchor():
        with boa.env.prank(user):
            c_amount = int(2 * 1e6 * 1e18 * 1.5 / 3000)
            debt = market_controller.debt(user)
            to_repay = debt // 2

            n_before_0, n_before_1 = market_amm.read_user_tick_numbers(user)
            stablecoin.approve(market_controller, 2**256-1)
            market_controller.repay(to_repay, user)
            n_after_0, n_after_1 = market_amm.read_user_tick_numbers(user)

            assert n_before_1 - n_before_0 + 1 == 5
            assert n_after_1 - n_after_0 + 1 == 5
            assert n_after_0 > n_before_0

            assert market_controller.debt(user) == debt - to_repay
            assert stablecoin.balanceOf(user) == debt - to_repay
            assert collateral_token.balanceOf(user) == 0
            assert stablecoin.balanceOf(market_amm) == 0
            assert collateral_token.balanceOf(market_amm) == c_amount
            assert market_controller.total_debt() == debt - to_repay


def test_add_collateral(stablecoin, collateral_token, market_controller, existing_loan, market_amm, accounts):
    user = accounts[0]

    with boa.env.anchor():
        c_amount = int(2 * 1e6 * 1e18 * 1.5 / 3000)
        debt = market_controller.debt(user)

        n_before_0, n_before_1 = market_amm.read_user_tick_numbers(user)
        with boa.env.prank(user):
            boa.deal(collateral_token, user, c_amount)
            market_controller.add_collateral(c_amount, user)
        n_after_0, n_after_1 = market_amm.read_user_tick_numbers(user)

        assert n_before_1 - n_before_0 + 1 == 5
        assert n_after_1 - n_after_0 + 1 == 5
        assert n_after_0 > n_before_0

        assert market_controller.debt(user) == debt
        assert stablecoin.balanceOf(user) == debt
        assert collateral_token.balanceOf(user) == 0
        assert stablecoin.balanceOf(market_amm) == 0
        assert collateral_token.balanceOf(market_amm) == 2 * c_amount
        assert market_controller.total_debt() == debt


def test_borrow_more(stablecoin, collateral_token, market_controller, existing_loan, market_amm, accounts):
    user = accounts[0]

    with boa.env.anchor():
        with boa.env.prank(user):
            debt = market_controller.debt(user)
            more_debt = debt // 10
            c_amount = int(2 * 1e6 * 1e18 * 1.5 / 3000)

            n_before_0, n_before_1 = market_amm.read_user_tick_numbers(user)
            market_controller.borrow_more(0, more_debt)
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
