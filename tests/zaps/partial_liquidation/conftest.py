import boa
import pytest

from tests.utils.deployers import (
    PARTIAL_REPAY_ZAP_DEPLOYER,
    PARTIAL_REPAY_ZAP_CALLBACK_DEPLOYER,
)


@pytest.fixture(scope="module")
def partial_repay_zap(admin):
    with boa.env.prank(admin):
        return PARTIAL_REPAY_ZAP_DEPLOYER.deploy(5 * 10**16, 1 * 10**16)


@pytest.fixture(scope="module")
def partial_repay_zap_callback(admin):
    with boa.env.prank(admin):
        return PARTIAL_REPAY_ZAP_CALLBACK_DEPLOYER.deploy(5 * 10**16, 1 * 10**16)


@pytest.fixture(scope="module")
def partial_repay_zap_tester(admin):
    with boa.env.prank(admin):
        return boa.load("contracts/testing/zaps/PartialRepayZapTester.vy")


@pytest.fixture(scope="module")
def controller_for_liquidation(
    borrowed_token,
    collateral_token,
    controller,
    amm,
    monetary_policy,
    admin,
):
    def f(sleep_time, user):
        N = 5
        collateral_amount = 10**18

        with boa.env.prank(admin):
            controller.set_amm_fee(10**6)
            monetary_policy.set_rate(int(1e18 * 1.0 / 365 / 86400))  # 100% APY

        debt = controller.max_borrowable(collateral_amount, N)
        with boa.env.prank(user):
            boa.deal(collateral_token, user, collateral_amount)
            borrowed_token.approve(amm, 2**256 - 1)
            borrowed_token.approve(controller, 2**256 - 1)
            collateral_token.approve(controller, 2**256 - 1)
            controller.create_loan(collateral_amount, debt, N)

        health_0 = controller.health(user)
        with boa.env.prank(user):
            amm.exchange(0, 1, debt, 0)
        health_1 = controller.health(user)

        assert health_0 <= health_1

        boa.env.time_travel(sleep_time)

        health_2 = controller.health(user)
        assert 0 < health_2 < controller.liquidation_discount()

        with boa.env.prank(admin):
            monetary_policy.set_rate(0)

        return controller

    return f
