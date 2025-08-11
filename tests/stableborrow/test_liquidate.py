import pytest
import boa
from boa import BoaError
from hypothesis import given, settings
from hypothesis import strategies as st
from ..conftest import approx
from tests.utils.constants import ZERO_ADDRESS


N = 5


@pytest.fixture(scope="module")
def controller_for_liquidation(stablecoin, collateral_token, market_controller, market_amm,
                               price_oracle, monetary_policy, admin, accounts):
    def f(sleep_time, discount):
        user = admin
        user2 = accounts[2]
        fee_receiver = accounts[0]  # same as liquidator
        collateral_amount = 10**18
        with boa.env.prank(admin):
            market_controller.set_amm_fee(10**6)
            monetary_policy.set_rate(int(1e18 * 1.0 / 365 / 86400))  # 100% APY
            collateral_token._mint_for_testing(user, collateral_amount)
            collateral_token._mint_for_testing(user2, collateral_amount)
            stablecoin.approve(market_amm, 2**256-1)
            stablecoin.approve(market_controller, 2**256-1)
            collateral_token.approve(market_controller, 2**256-1)
        with boa.env.prank(user2):
            collateral_token.approve(market_controller, 2**256-1)
        debt = market_controller.max_borrowable(collateral_amount, N)

        with boa.env.prank(user):
            market_controller.create_loan(collateral_amount, debt, N)
        health_0 = market_controller.health(user)
        # We put mostly USD into AMM, and its quantity remains constant while
        # interest is accruing. Therefore, we will be at liquidation at some point
        with boa.env.prank(user):
            market_amm.exchange(0, 1, debt, 0)
        health_1 = market_controller.health(user)

        assert health_0 <= health_1  # Eearns fees on dynamic fee

        boa.env.time_travel(sleep_time)

        health_2 = market_controller.health(user)
        # Still healthy but liquidation threshold satisfied
        assert health_2 < discount
        if discount > 0:
            assert health_2 > 0

        with boa.env.prank(admin):
            # Stop charging fees to have enough coins to liquidate in existence a block before
            monetary_policy.set_rate(0)

            market_controller.collect_fees()
            # Check that we earned the same in admin fees as we need to liquidate
            # Calculation is not precise because of dead shares, but the last withdrawal will put dust in admin fees
            assert approx(stablecoin.balanceOf(fee_receiver), market_controller.tokens_to_liquidate(user), 1e-10)

        # Borrow some more funds to repay for our overchargings with DEAD_SHARES
        with boa.env.prank(user2):
            market_controller.create_loan(collateral_amount, debt, N)

        return market_controller

    return f


def test_liquidate(accounts, admin, controller_for_liquidation, market_amm, stablecoin):
    user = admin
    fee_receiver = accounts[0]

    controller = controller_for_liquidation(sleep_time=80 * 86400, discount=0)
    x = market_amm.get_sum_xy(user)[0]

    with boa.env.prank(accounts[2]):
        stablecoin.transfer(fee_receiver, 10**10)

    with boa.env.prank(fee_receiver):
        with boa.reverts("Slippage"):
            controller.liquidate(user, x + 1)
        controller.liquidate(user, int(x * 0.999999))


@given(frac=st.integers(min_value=0, max_value=11 * 10**17))
@settings(max_examples=200)
def test_liquidate_callback(accounts, admin, stablecoin, collateral_token, controller_for_liquidation, market_amm, fake_leverage, frac):
    user = admin
    fee_receiver = accounts[0]
    ld = int(0.02 * 1e18)
    if frac < 10**18:
        # f = ((1 + h/2) / (1 + h) * (1 - frac) + frac) * frac
        f = ((10 ** 18 + ld // 2) * (10 ** 18 - frac) // (10 ** 18 + ld) + frac) * frac // 10 ** 18 // 5 * 5  # The latter part is rounding off for multiple bands
    else:
        f = 10**18
    # Partial liquidation improves health.
    # In case AMM has stablecoins in addition to collateral (our test), it means more stablecoins there.
    # But that requires more stablecoins than exist.
    # Therefore, we make more stablecoins if liquidation is partial

    controller = controller_for_liquidation(sleep_time=45 * 86400, discount=0)
    # Health here is not too bad, so we still can profitably liquidate
    x = market_amm.get_sum_xy(user)[0]

    with boa.env.prank(accounts[2]):
        stablecoin.transfer(fee_receiver, 10**10)

    with boa.env.prank(fee_receiver):
        # Prepare stablecoins to use for liquidation
        # we do it by borrowing
        if f != 10**18:
            with boa.env.prank(fee_receiver):
                collateral_token._mint_for_testing(fee_receiver, 10**18)
                collateral_token.approve(controller.address, 2**256-1)
                debt2 = controller.max_borrowable(10**18, 5)
                controller.create_loan(10**18, debt2, 5)
                stablecoin.transfer(fake_leverage.address, debt2)

        with boa.reverts("Slippage"):
            controller.liquidate(user, x + 1)
        b = stablecoin.balanceOf(fee_receiver)
        stablecoin.transfer(fake_leverage.address, b)
        health_before = controller.health(user)
        try:
            dy = collateral_token.balanceOf(fee_receiver)
            controller.liquidate_extended(user, int(0.999 * f * x / 1e18), frac,
                                          fake_leverage.address, [])
            dy = collateral_token.balanceOf(fee_receiver) - dy
            dx = stablecoin.balanceOf(fee_receiver) - b
            if f > 0:
                p = market_amm.get_p() / 1e18
                assert dy * p + dx > 0, "Liquidator didn't make money"
            if f != 10**18 and f > 0:
                assert controller.health(user) > health_before
        except BoaError as e:
            if frac == 0 and "Loan doesn't exist" in str(e):
                pass
            elif frac * controller.debt(user) // 10**18 == 0:
                pass
            else:
                raise


def test_self_liquidate(accounts, admin, controller_for_liquidation, market_amm, stablecoin):
    user = admin
    fee_receiver = accounts[0]

    with boa.env.anchor():
        controller = controller_for_liquidation(sleep_time=40 * 86400, discount=2.5 * 10**16)

        with boa.env.prank(accounts[2]):
            stablecoin.transfer(fee_receiver, 10**10)

        x = market_amm.get_sum_xy(user)[0]
        with boa.env.prank(fee_receiver):
            stablecoin.transfer(user, stablecoin.balanceOf(fee_receiver))

        with boa.env.prank(accounts[1]):
            with boa.reverts("Not enough rekt"):
                controller.liquidate(user, 0)

        with boa.env.prank(user):
            with boa.reverts("Slippage"):
                controller.liquidate(user, x + 1)

            controller.liquidate(user, int(x * 0.999999))


@given(frac=st.integers(min_value=10**14, max_value=10**18 - 13))
def test_tokens_to_liquidate(accounts, admin, controller_for_liquidation, market_amm, stablecoin, frac):
    user = admin
    fee_receiver = accounts[0]

    with boa.env.anchor():
        controller = controller_for_liquidation(sleep_time=80 * 86400, discount=0)
        initial_balance = stablecoin.balanceOf(fee_receiver)
        tokens_to_liquidate = controller.tokens_to_liquidate(user, frac)

        with boa.env.prank(accounts[2]):
            stablecoin.transfer(fee_receiver, 10**10)

        with boa.env.prank(fee_receiver):
            controller.liquidate_extended(user, 0, frac, ZERO_ADDRESS, [])

        balance = stablecoin.balanceOf(fee_receiver)

        if frac < 10**18:
            assert approx(balance, initial_balance - tokens_to_liquidate, 1e5, abs_precision=1e5)
        else:
            assert balance != initial_balance - tokens_to_liquidate
