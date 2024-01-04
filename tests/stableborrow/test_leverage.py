import boa
from ..conftest import approx

from hypothesis import given, settings
from hypothesis import strategies as st


def test_leverage(collateral_token, stablecoin, market_controller, market_amm, fake_leverage, accounts):
    user = accounts[0]
    amount = 10 * 10**18

    controller_mint = stablecoin.balanceOf(market_controller.address)

    with boa.env.prank(user):
        collateral_token._mint_for_testing(user, amount)

        market_controller.create_loan_extended(amount, amount * 2 * 3000, 5, fake_leverage.address, [int(amount * 1.5)])
        assert collateral_token.balanceOf(user) == 0
        assert collateral_token.balanceOf(market_amm.address) == 3 * amount
        assert market_amm.get_sum_xy(user) == [0, 3 * amount]
        assert market_controller.debt(user) == amount * 2 * 3000
        assert stablecoin.balanceOf(user) == 0

        market_controller.repay_extended(fake_leverage.address, [10**18])
        assert market_controller.debt(user) == 0
        assert collateral_token.balanceOf(market_amm.address) == 0
        assert stablecoin.balanceOf(market_amm.address) == 0
        assert market_amm.get_sum_xy(user) == [0, 0]
        assert collateral_token.balanceOf(market_controller.address) == 0
        assert stablecoin.balanceOf(market_controller.address) == controller_mint
        assert collateral_token.balanceOf(user) == amount
        assert stablecoin.balanceOf(user) == 0


@given(
    amount=st.integers(min_value=10 * 10**8, max_value=10**18),
    loan_mul=st.floats(min_value=0, max_value=10.0),
    repay_mul=st.floats(min_value=0, max_value=1.0))
@settings(max_examples=2000)
def test_leverage_property(collateral_token, stablecoin, market_controller, market_amm, fake_leverage, accounts,
                           amount, loan_mul, repay_mul):
    user = accounts[0]

    with boa.env.prank(user):
        collateral_token._mint_for_testing(user, amount)

        debt = int(loan_mul * amount * 3000)
        if (debt // 3000) <= collateral_token.balanceOf(fake_leverage.address) and debt > 0:
            market_controller.create_loan_extended(amount, debt, 5, fake_leverage.address, [0])
        else:
            with boa.reverts():
                market_controller.create_loan_extended(amount, debt, 5, fake_leverage.address, [0])
            return
        assert collateral_token.balanceOf(user) == 0
        expected_collateral = int((1 + loan_mul) * amount)
        assert approx(collateral_token.balanceOf(market_amm.address), expected_collateral, 1e-9, 10)
        xy = market_amm.get_sum_xy(user)
        assert xy[0] == 0
        assert approx(xy[1], expected_collateral, 1e-9, 10)
        assert approx(market_controller.debt(user), debt, 1e-9, 10)
        assert stablecoin.balanceOf(user) == 0

        s0 = stablecoin.balanceOf(market_controller.address)

        if debt * int(repay_mul * 1e18) // 10**18 >= 1:
            market_controller.repay_extended(fake_leverage.address, [int(repay_mul * 1e18)])
        else:
            with boa.reverts():
                market_controller.repay_extended(fake_leverage.address, [int(repay_mul * 1e18)])
            return
        assert market_controller.debt(user) == debt - debt * int(repay_mul * 1e18) // 10**18
        if repay_mul == 1.0:
            assert collateral_token.balanceOf(market_amm.address) == 0
            assert stablecoin.balanceOf(market_amm.address) == 0
            assert market_amm.get_sum_xy(user) == [0, 0]
        assert collateral_token.balanceOf(market_controller.address) == 0
        assert stablecoin.balanceOf(market_controller.address) - s0 == debt * int(repay_mul * 1e18) // 10**18
        if repay_mul == 1.0:
            assert collateral_token.balanceOf(user) == amount
        else:
            assert collateral_token.balanceOf(user) == 0


def test_deleverage_error(collateral_token, stablecoin, market_controller, market_amm, fake_leverage, accounts):
    test_leverage_property.hypothesis.inner_test(
            collateral_token, stablecoin, market_controller, market_amm, fake_leverage, accounts, 1000000000, 1.0, 0.5)


def test_no_coins_to_repay(collateral_token, stablecoin, market_controller, market_amm, fake_leverage, accounts):
    test_leverage_property.hypothesis.inner_test(
            collateral_token, stablecoin, market_controller, market_amm, fake_leverage, accounts, 128102389400761, 2.0,
            1.3010426069826053e-18)
