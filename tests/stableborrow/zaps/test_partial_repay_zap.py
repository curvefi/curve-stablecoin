import boa
import hashlib
import pytest
from eth_abi import encode


@pytest.fixture(scope="module")
def dummy_router(admin):
    with boa.env.prank(admin):
        return boa.load("contracts/testing/DummyRouter.vy")


@pytest.fixture(scope="module")
def get_partial_repay_zap(admin, collateral_token, stablecoin, dummy_router):
    def deploy_partial_repay_zap(controller_address):
        with boa.env.prank(admin):
            return boa.load(
                "contracts/zaps/PartialRepayZap.vy",
                str(dummy_router.address),
                controller_address,
                stablecoin.address,
                collateral_token.address
            )
    return deploy_partial_repay_zap


def encode_data_for_router(router, _x: str, _y: str, _in_amount: int, _out_amount: int) -> bytes:
    return router.exchange.prepare_calldata(_x, _y, _in_amount, _out_amount)


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
    def f(sleep_time, user):
        N = 5
        collateral_amount = 10**18

        with boa.env.prank(admin):
            market_controller.set_amm_fee(10**6)
            monetary_policy.set_rate(int(1e18 * 1.0 / 365 / 86400))  # 100% APY

        debt = market_controller.max_borrowable(collateral_amount, N)
        with boa.env.prank(user):
            collateral_token._mint_for_testing(user, collateral_amount)
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

        return market_controller

    return f


def test_self_liquidate(
    stablecoin,
    collateral_token,
    controller_for_liquidation,
    market_amm,
    accounts,
    get_partial_repay_zap,
    dummy_router,
):
    user = accounts[1]
    controller = controller_for_liquidation(sleep_time=int(42 * 86400), user=user)
    partial_repay_zap = get_partial_repay_zap(controller.address)
    someone_else = str(partial_repay_zap.address)

    controller.approve(someone_else, True, sender=user)

    h = controller.health(user) / 10**16
    assert 0 < h < 1

    frac = 0.07
    collateral = controller.user_state(user)[0]
    collateral_in = int(((1 + h / 2) / (1 + h) * (1 - frac) + frac) * frac * collateral)
    stablecoin_out = 10000 * collateral_in

    # Ensure router has stablecoin
    with boa.env.prank(dummy_router.address):
        collateral_token._mint_for_testing(dummy_router, 10**21)
        collateral_token.approve(controller, 2**256 - 1)
        controller.create_loan(10**20, controller.max_borrowable(10**20, 5), 5)

    partial_repay_zap.repay_from_position(
        0,
        encode_data_for_router(
            dummy_router,
            str(collateral_token.address),
            str(stablecoin.address),
            collateral_in,
            stablecoin_out,
        ),
        int(frac * 10**18),
        sender=user,
    )

    h = controller.health(user) / 10 ** 16
    assert h > 3
