import boa
import pytest


@pytest.fixture(scope="module")
def existing_loan(collateral_token, stablecoin, market_controller, accounts):
    user = accounts[0]
    c_amount = int(2 * 1e6 * 10 ** collateral_token.decimals() * 1.5 / 3000)
    l_amount = 5 * 10**5 * 10 ** stablecoin.decimals()
    n = 5

    with boa.env.prank(user):
        boa.deal(collateral_token, user, c_amount)
        market_controller.create_loan(c_amount, l_amount, n)


def test_create_loan(
    controller_factory,
    stablecoin,
    collateral_token,
    market_controller,
    market_amm,
    monetary_policy,
    accounts,
):
    user = accounts[0]
    someone_else = accounts[1]

    initial_amount = 10**25
    c_amount = int(2 * 1e6 * 10 ** collateral_token.decimals() * 1.5 / 3000)
    l_amount = 5 * 10**5 * 10 ** stablecoin.decimals()

    with boa.env.prank(user):
        with boa.env.anchor():
            boa.deal(collateral_token, user, initial_amount)
            market_controller.create_loan(c_amount, l_amount, 5)

    boa.deal(collateral_token, someone_else, initial_amount)

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


def test_repay_all(
    stablecoin, collateral_token, market_controller, existing_loan, accounts
):
    user = accounts[0]
    someone_else = accounts[1]
    c_amount = int(2 * 1e6 * 10 ** collateral_token.decimals() * 1.5 / 3000)
    amm = market_controller.amm()

    with boa.env.prank(user):
        stablecoin.transfer(someone_else, stablecoin.balanceOf(user))

    with boa.env.prank(user):
        market_controller.approve(someone_else, True)

    # In this particular case, it could have been easily removed without approval, too
    # because health is still good and loan is not underwater

    with boa.env.prank(someone_else):
        stablecoin.approve(market_controller, 2**256 - 1)
        market_controller.repay(2**100, user)
        assert market_controller.debt(user) == 0
        assert stablecoin.balanceOf(user) == 0
        assert collateral_token.balanceOf(user) == c_amount
        assert stablecoin.balanceOf(amm) == 0
        assert collateral_token.balanceOf(amm) == 0
        assert market_controller.total_debt() == 0


def test_borrow_more(
    stablecoin, collateral_token, market_controller, existing_loan, market_amm, accounts
):
    user = accounts[0]
    someone_else = accounts[1]

    debt = market_controller.debt(user)
    more_debt = debt // 10
    c_amount = int(2 * 1e6 * 10 ** collateral_token.decimals() * 1.5 / 3000)

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


def test_remove_collateral(
    stablecoin, collateral_token, market_controller, existing_loan, market_amm, accounts
):
    user = accounts[0]
    someone_else = accounts[1]

    debt = market_controller.debt(user)
    c_amount = int(2 * 1e6 * 10 ** collateral_token.decimals() * 1.5 / 3000)

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


@pytest.fixture(scope="module")
def controller_for_liquidation(
    stablecoin,
    collateral_token,
    market_controller,
    market_amm,
    price_oracle,
    monetary_policy,
    admin,
):
    def f(sleep_time, user, someone_else):
        N = 5
        collateral_amount = 10 ** collateral_token.decimals()

        with boa.env.prank(admin):
            market_controller.set_amm_fee(10**6)
            monetary_policy.set_rate(int(1e18 * 1.0 / 365 / 86400))  # 100% APY

        debt = market_controller.max_borrowable(collateral_amount, N)
        with boa.env.prank(user):
            boa.deal(collateral_token, user, collateral_amount)
            stablecoin.approve(market_amm, 2**256 - 1)
            stablecoin.approve(market_controller, 2**256 - 1)
            collateral_token.approve(market_controller, 2**256 - 1)
            market_controller.create_loan(collateral_amount, debt, N)

        health_0 = market_controller.health(user)
        # We put mostly USD into AMM, and its quantity remains constant while
        # interest is accruing. Therefore, we will be at liquidation at some point
        with boa.env.prank(user):
            market_amm.exchange(0, 1, debt, 0)
        health_1 = market_controller.health(user)

        assert health_0 <= health_1  # Earns fees on dynamic fee

        boa.env.time_travel(sleep_time)

        health_2 = market_controller.health(user)
        # Still healthy but liquidation threshold satisfied
        assert 0 < health_2 < market_controller.liquidation_discount()

        with boa.env.prank(admin):
            # Stop charging fees to have enough coins to liquidate in existence a block before
            monetary_policy.set_rate(0)

        # Ensure approved account has enough to liquidate
        boa.deal(stablecoin, someone_else, debt)

        return market_controller

    return f


def test_self_liquidate(
    stablecoin, collateral_token, controller_for_liquidation, market_amm, accounts
):
    user = accounts[1]
    someone_else = accounts[2]
    controller = controller_for_liquidation(
        sleep_time=30 * 86400, user=user, someone_else=someone_else
    )

    x = market_amm.get_sum_xy(user)[0]

    with boa.env.prank(someone_else):
        with boa.reverts("Not enough rekt"):
            controller.liquidate(user, 0)

    with boa.env.prank(user):
        controller.approve(someone_else, True)

    with boa.env.prank(someone_else):
        with boa.reverts("Slippage"):
            controller.liquidate(user, x + 1)

        controller.liquidate(user, int(x * 0.999999))
        assert controller.loan_exists(user) is False
