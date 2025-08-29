import boa
import pytest


@pytest.fixture(scope="module")
def get_partial_repay_zap(admin, collateral_token, stablecoin, dummy_router):
    def deploy_partial_repay_zap(controller_address, amm_address):
        with boa.env.prank(admin):
            return boa.load(
                "contracts/zaps/PartialRepayZap.vy",
                str(dummy_router.address),
                controller_address,
                amm_address,
                stablecoin.address,
                collateral_token.address,
                5 * 10 ** 16,
                1 * 10 ** 16,
            )

    return deploy_partial_repay_zap


@pytest.fixture(scope="module")
def controller_for_liquidation(
    borrowed_token,
    collateral_token,
    market_controller,
    market_amm,
    price_oracle,
    monetary_policy,
    admin,
):
    def f(sleep_time, user):
        N = 5
        collateral_amount = 10**18

        with boa.env.prank(admin):
            market_controller.set_amm_fee(10**6)
            monetary_policy.set_rate(int(1e18 * 1.0 / 365 / 86400))  # 100% APY

        debt = market_controller.max_borrowable(collateral_amount, N)
        with boa.env.prank(user):
            collateral_token._mint_for_testing(user, collateral_amount)
            borrowed_token.approve(market_amm, 2**256 - 1)
            borrowed_token.approve(market_controller, 2**256 - 1)
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

        return market_controller

    return f


def test_self_liquidate(
    borrowed_token,
    collateral_token,
    controller_for_liquidation,
    market_amm,
    accounts,
    get_partial_repay_zap,
    dummy_router,
):
    user = accounts[1]
    liquidator = accounts[2]
    controller = controller_for_liquidation(sleep_time=int(42 * 86400), user=user)
    partial_repay_zap = get_partial_repay_zap(controller.address, controller.amm)
    someone_else = str(partial_repay_zap.address)

    controller.approve(someone_else, True, sender=user)

    h = controller.health(user) / 10**16
    assert 0 < h < 1

    frac = 0.05

    h_norm = h * 10**16
    frac_norm = frac * 10**18
    collateral = controller.user_state(user)[0]
    collateral_in = int(
        ((10**18 + h_norm // 2) * (10**18 - frac_norm) // (10**18 + h_norm) + frac_norm)
        * frac_norm
        * collateral
        // 10**36
    )
    stablecoin_out = 10000 * collateral_in

    # Ensure router has stablecoin
    with boa.env.prank(liquidator):
        collateral_token._mint_for_testing(dummy_router, 10**21)
        collateral_token.approve(controller, 2**256 - 1)
        controller.create_loan(10**20, controller.max_borrowable(10**20, 5), 5)

    partial_repay_zap.repay_from_position(
        user,
        0,
        sender=liquidator,
    )

    h = controller.health(user) / 10**16
    assert h > 3
