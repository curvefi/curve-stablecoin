import boa
import pytest


@pytest.fixture(scope="module")
def partial_repay_zap(admin):
    with boa.env.prank(admin):
        return boa.load("contracts/zaps/PartialRepayZap.vy", 5 * 10**16, 1 * 10**16)


@pytest.fixture(scope="module")
def controller_for_liquidation(
    borrowed_token,
    collateral_token,
    filled_controller,
    market_amm,
    price_oracle,
    market_mpolicy,
    admin,
):
    def f(sleep_time, user):
        N = 5
        collateral_amount = 10**18

        with boa.env.prank(admin):
            filled_controller.set_amm_fee(10**6)
            market_mpolicy.set_rate(int(1e18 * 1.0 / 365 / 86400))  # 100% APY

        debt = filled_controller.max_borrowable(collateral_amount, N)
        with boa.env.prank(user):
            boa.deal(collateral_token, user, collateral_amount)
            borrowed_token.approve(market_amm, 2**256 - 1)
            borrowed_token.approve(filled_controller, 2**256 - 1)
            collateral_token.approve(filled_controller, 2**256 - 1)
            filled_controller.create_loan(collateral_amount, debt, N)

        health_0 = filled_controller.health(user)
        # We put mostly USD into AMM, and its quantity remains constant while
        # interest is accruing. Therefore, we will be at liquidation at some point
        with boa.env.prank(user):
            market_amm.exchange(0, 1, debt, 0)
        health_1 = filled_controller.health(user)

        assert health_0 <= health_1  # Earns fees on dynamic fee

        boa.env.time_travel(sleep_time)

        health_2 = filled_controller.health(user)
        # Still healthy but liquidation threshold satisfied
        assert 0 < health_2 < filled_controller.liquidation_discount()

        with boa.env.prank(admin):
            # Stop charging fees to have enough coins to liquidate in existence a block before
            market_mpolicy.set_rate(0)

        return filled_controller

    return f


@pytest.mark.parametrize("is_approved", [True, False])
def test_users_to_liquidate(
    borrowed_token,
    collateral_token,
    controller_for_liquidation,
    market_amm,
    accounts,
    partial_repay_zap,
    is_approved,
):
    user = accounts[1]
    controller = controller_for_liquidation(sleep_time=int(36.1 * 86400), user=user)

    if is_approved:
        someone_else = str(partial_repay_zap.address)
        controller.approve(someone_else, True, sender=user)

    users_to_liquidate = partial_repay_zap.users_to_liquidate(controller.address)

    if not is_approved:
        assert users_to_liquidate == []
    else:
        assert len(users_to_liquidate) == 1
        assert users_to_liquidate[0][0] == user


def test_liquidate_partial(
    borrowed_token,
    collateral_token,
    controller_for_liquidation,
    market_amm,
    accounts,
    partial_repay_zap,
):
    user = accounts[1]
    liquidator = accounts[2]
    controller = controller_for_liquidation(sleep_time=int(36.1 * 86400), user=user)
    someone_else = str(partial_repay_zap.address)
    controller.approve(someone_else, True, sender=user)

    h = controller.health(user) / 10**16
    assert 0.9 < h < 1

    # Ensure liquidator has stablecoin
    boa.deal(borrowed_token, liquidator, 10**21)
    with boa.env.prank(liquidator):
        borrowed_token.approve(partial_repay_zap.address, 2**256 - 1)
        partial_repay_zap.liquidate_partial(controller.address, user, 0)

    h = controller.health(user) / 10**16
    assert h > 1
