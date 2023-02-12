import boa
from datetime import timedelta
from .conftest import get_method_id
from ..conftest import approx

from hypothesis import given, settings
from hypothesis import strategies as st


leverage_method = get_method_id("leverage(address,uint256,uint256,uint256,uint256[])")  # min_amount for output collateral
deleverage_method = get_method_id("deleverage(address,uint256,uint256,uint256,uint256[])")  # min_amount for stablecoins


def test_leverage(collateral_token, stablecoin, market_controller, market_amm, fake_leverage, accounts):
    user = accounts[0]
    amount = 10 * 10**18

    controller_mint = stablecoin.balanceOf(market_controller.address)

    with boa.env.prank(user):
        collateral_token._mint_for_testing(user, amount)

        market_controller.create_loan_extended(amount, amount * 2 * 3000, 5, fake_leverage.address, leverage_method, [int(amount * 1.5)])
        assert collateral_token.balanceOf(user) == 0
        assert collateral_token.balanceOf(market_amm.address) == 3 * amount
        assert market_amm.get_sum_xy(user) == (0, 3 * amount)
        assert market_controller.debt(user) == amount * 2 * 3000
        assert stablecoin.balanceOf(user) == 0

        market_controller.repay_extended(fake_leverage.address, deleverage_method, [int(0.8 * amount * 2 * 3000)])
        assert market_controller.debt(user) == 0
        assert collateral_token.balanceOf(market_amm.address) == 0
        assert stablecoin.balanceOf(market_amm.address) == 0
        assert market_amm.get_sum_xy(user) == (0, 0)
        assert collateral_token.balanceOf(market_controller.address) == 0
        assert stablecoin.balanceOf(market_controller.address) == controller_mint
        assert collateral_token.balanceOf(user) == amount
        assert stablecoin.balanceOf(user) == 0


@given(
    amount=st.integers(min_value=10 * 10**8, max_value=10**18),
    loan_mul=st.floats(min_value=0, max_value=10.0))
@settings(deadline=timedelta(seconds=1000), max_examples=200)
def test_leverage_property(collateral_token, stablecoin, market_controller, market_amm, fake_leverage, accounts,
                           amount, loan_mul):
    user = accounts[0]

    with boa.env.prank(user):
        collateral_token._mint_for_testing(user, amount)

        debt = int(loan_mul * amount * 3000)
        if (debt // 3000) <= collateral_token.balanceOf(fake_leverage.address) and debt > 0:
            market_controller.create_loan_extended(amount, debt, 5, fake_leverage.address, leverage_method, [0])
        else:
            with boa.reverts():
                market_controller.create_loan_extended(amount, debt, 5, fake_leverage.address, leverage_method, [0])
            return
        assert collateral_token.balanceOf(user) == 0
        expected_collateral = int((1 + loan_mul) * amount)
        assert approx(collateral_token.balanceOf(market_amm.address), expected_collateral, 1e-9, 10)
        xy = market_amm.get_sum_xy(user)
        assert xy[0] == 0
        assert approx(xy[1], expected_collateral, 1e-9, 10)
        assert approx(market_controller.debt(user), int(amount * loan_mul * 3000), 1e-9, 10)
        assert stablecoin.balanceOf(user) == 0
