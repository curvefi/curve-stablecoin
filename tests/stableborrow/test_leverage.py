import boa
import pytest
from eth_abi import encode

from hypothesis import given, settings
from hypothesis import strategies as st


def test_leverage(collateral_token, stablecoin, market_controller, market_amm, fake_leverage, accounts):
    user = accounts[0]
    amount = 10 * 10**18

    controller_mint = stablecoin.balanceOf(market_controller.address)

    with boa.env.prank(user):
        boa.deal(collateral_token, user, amount)

        calldata = encode(["uint256"], [int(amount * 1.5)])
        fake_leverage_balances1 = [stablecoin.balanceOf(fake_leverage), collateral_token.balanceOf(fake_leverage)]
        market_controller.create_loan(amount, amount * 2 * 3000, 5, user, fake_leverage.address, calldata)
        fake_leverage_balances2 = [stablecoin.balanceOf(fake_leverage), collateral_token.balanceOf(fake_leverage)]
        assert collateral_token.balanceOf(market_amm.address) == 3 * amount
        assert market_amm.get_sum_xy(user) == [0, 3 * amount]
        assert market_controller.debt(user) == amount * 2 * 3000
        assert stablecoin.balanceOf(user) == 0
        assert collateral_token.balanceOf(user) == 0
        assert fake_leverage_balances2[0] - fake_leverage_balances1[0] == amount * 2 * 3000, 5
        assert fake_leverage_balances1[1] - fake_leverage_balances2[1] == 2 * amount

        calldata = encode(["uint256"], [10**18])
        market_controller.repay(0, user, market_amm.active_band(), fake_leverage.address, calldata)
        fake_leverage_balances3 = [stablecoin.balanceOf(fake_leverage), collateral_token.balanceOf(fake_leverage)]
        assert market_controller.debt(user) == 0
        assert collateral_token.balanceOf(market_amm.address) == 0
        assert stablecoin.balanceOf(market_amm.address) == 0
        assert market_amm.get_sum_xy(user) == [0, 0]
        assert collateral_token.balanceOf(market_controller.address) == 0
        assert stablecoin.balanceOf(market_controller.address) == controller_mint
        assert stablecoin.balanceOf(user) == 0
        assert collateral_token.balanceOf(user) == amount
        assert fake_leverage_balances3[0] == fake_leverage_balances1[0]
        assert fake_leverage_balances3[1] == fake_leverage_balances1[1]


@given(
    amount=st.integers(min_value=10 * 10**8, max_value=10**18),
    loan_mul=st.floats(min_value=0, max_value=10.0),
    loan_more_mul=st.floats(min_value=0, max_value=10.0),
    repay_mul=st.floats(min_value=0, max_value=1.0))
@settings(max_examples=2000)
def test_leverage_property(collateral_token, stablecoin, market_controller, market_amm, fake_leverage, accounts,
                           amount, loan_mul, loan_more_mul, repay_mul):
    user = accounts[0]

    with boa.env.prank(user):
        boa.deal(collateral_token, user, amount)

        debt = int(loan_mul * amount * 3000)
        calldata = encode(["uint256"], [0])
        if (debt // 3000) <= collateral_token.balanceOf(fake_leverage.address) and debt > 0:
            market_controller.create_loan(amount, debt, 5, user, fake_leverage.address, calldata)
        else:
            with boa.reverts():
                market_controller.create_loan(amount, debt, 5, user, fake_leverage.address, calldata)
            return
        assert collateral_token.balanceOf(user) == 0
        expected_collateral = int((1 + loan_mul) * amount)
        assert collateral_token.balanceOf(market_amm.address) == pytest.approx(expected_collateral, rel=1e-9, abs=10)
        xy = market_amm.get_sum_xy(user)
        assert xy[0] == 0
        assert xy[1] == pytest.approx(expected_collateral, rel=1e-9, abs=10)
        assert market_controller.debt(user) == pytest.approx(debt, rel=1e-9, abs=10)
        assert stablecoin.balanceOf(user) == 0

        more_debt = int(loan_more_mul * amount * 3000)
        if (more_debt // 3000) <= collateral_token.balanceOf(fake_leverage.address):
            if more_debt > 0:
                boa.deal(collateral_token, user, amount)
            market_controller.borrow_more(amount, more_debt, user, fake_leverage.address, calldata)
            debt += more_debt
            if more_debt > 0:
                assert collateral_token.balanceOf(user) == 0
                expected_collateral = int((2 + loan_mul + loan_more_mul) * amount)
                assert collateral_token.balanceOf(market_amm.address) == pytest.approx(expected_collateral, rel=1e-9, abs=10)
                xy = market_amm.get_sum_xy(user)
                assert xy[0] == 0
                assert xy[1] == pytest.approx(expected_collateral, rel=1e-9, abs=10)
                assert market_controller.debt(user) == pytest.approx(debt, rel=1e-9, abs=10)
                assert stablecoin.balanceOf(user) == 0

        else:
            with boa.reverts():
                market_controller.borrow_more(amount, more_debt, user, fake_leverage.address, calldata)

        s0 = stablecoin.balanceOf(market_controller.address)

        calldata = encode(["uint256"], [int(repay_mul * 1e18)])
        if debt * int(repay_mul * 1e18) // 10**18 >= 1:
            market_controller.repay(0, user, market_amm.active_band(), fake_leverage.address, calldata)
        else:
            with boa.reverts():
                market_controller.repay(0, user, market_amm.active_band(), fake_leverage.address, calldata)
            return
        assert market_controller.debt(user) == debt - debt * int(repay_mul * 1e18) // 10**18
        if repay_mul == 1.0:
            assert collateral_token.balanceOf(market_amm.address) == 0
            assert stablecoin.balanceOf(market_amm.address) == 0
            assert market_amm.get_sum_xy(user) == [0, 0]
        assert collateral_token.balanceOf(market_controller.address) == 0
        assert stablecoin.balanceOf(market_controller.address) - s0 == debt * int(repay_mul * 1e18) // 10**18
        if repay_mul == 1.0:
            if more_debt > 0:
                assert abs(collateral_token.balanceOf(user) - 2 * amount) <= 1
            else:
                assert collateral_token.balanceOf(user) == amount
        else:
            assert collateral_token.balanceOf(user) == 0


def test_deleverage_error(collateral_token, stablecoin, market_controller, market_amm, fake_leverage, accounts):
    test_leverage_property.hypothesis.inner_test(
            collateral_token, stablecoin, market_controller, market_amm, fake_leverage, accounts, 1000000000, 1.0, 0, 0.5)


def test_no_coins_to_repay(collateral_token, stablecoin, market_controller, market_amm, fake_leverage, accounts):
    test_leverage_property.hypothesis.inner_test(
            collateral_token, stablecoin, market_controller, market_amm, fake_leverage, accounts, 128102389400761, 2.0,
            0, 1.3010426069826053e-18)
