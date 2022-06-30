import pytest
import brownie
from ..conftest import approx

N = 5


@pytest.fixture(scope="module")
def controller_for_liquidation(chain, stablecoin, collateral_token, market_controller, market_amm, PriceOracle, monetary_policy, accounts):
    def f(sleep_time, discount):
        user = accounts[0]
        fee_receiver = accounts[1]  # same as liquidator
        collateral_amount = 10**18
        market_controller.set_amm_fee(0, {'from': user})
        monetary_policy.set_rate(int(1e18 * 1.0 / 365 / 86400), {'from': user})  # 100% APY
        collateral_token._mint_for_testing(user, collateral_amount, {'from': user})
        stablecoin.approve(market_amm, 2**256-1, {'from': user})
        stablecoin.approve(market_amm, 2**256-1, {'from': fee_receiver})
        debt = market_controller.max_borrowable(collateral_amount, N)

        market_controller.create_loan(collateral_amount, debt, N, {'from': user})
        health_0 = market_controller.health(user)
        # We put mostly USD into AMM, and its quantity remains constant while
        # interest is accruing. Therefore, we will be at liquidation at some point
        market_amm.exchange(0, 1, debt, 0, {'from': user})
        health_1 = market_controller.health(user)

        assert approx(health_0, health_1, 1e-6)

        chain.sleep(sleep_time)
        chain.mine()

        health_2 = market_controller.health(user)
        # Still healthy but liquidation threshold satisfied
        assert health_2 < discount
        assert health_2 > 0

        # Stop charging fees to have enough coins to liquidate in existence a block before
        monetary_policy.set_rate(0, {'from': user})

        market_controller.collect_fees({'from': user})
        # Check that we earned exactly the same in admin fees as we need to liquidate
        assert stablecoin.balanceOf(fee_receiver) == market_controller.tokens_to_liquidate(user)

        return market_controller

    return f


def test_liquidate(accounts, controller_for_liquidation, market_amm):
    user, fee_receiver = accounts[:2]
    controller = controller_for_liquidation(sleep_time=40 * 86400, discount=10**16)
    x = market_amm.get_sum_xy(user)[0]

    with brownie.reverts("Sandwich"):
        controller.liquidate(user, x + 1, {'from': fee_receiver})

    controller.liquidate(user, x, {'from': fee_receiver})


def test_self_liquidate(accounts, controller_for_liquidation, market_amm, stablecoin):
    user, fee_receiver = accounts[:2]
    controller = controller_for_liquidation(sleep_time=35 * 86400, discount=3 * 10**16)

    x = market_amm.get_sum_xy(user)[0]
    stablecoin.transfer(user, stablecoin.balanceOf(fee_receiver), {'from': fee_receiver})

    with brownie.reverts("Not enough rekt"):
        controller.liquidate(user, 0, {'from': user})

    with brownie.reverts("Sandwich"):
        controller.self_liquidate(x + 1, {'from': user})

    controller.self_liquidate(x, {'from': user})
