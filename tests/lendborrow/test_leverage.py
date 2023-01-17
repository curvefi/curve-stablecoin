import boa
import pytest
from vyper.utils import abi_method_id


def get_method_id(desc):
    return abi_method_id(desc).to_bytes(4, 'big') + b'\x00' * 28


@pytest.fixture(scope="module")
def fake_leverage(stablecoin, collateral_token, market_controller, admin):
    with boa.env.prank(admin):
        leverage = boa.load('contracts/testing/FakeLeverage.vy', stablecoin.address, collateral_token.address,
                            market_controller.address, 3000 * 10**18)
        boa.env.set_balance(admin, 1000 * 10**18)
        collateral_token._mint_for_testing(leverage.address, 1000 * 10**18)
        return leverage


def test_leverage(collateral_token, stablecoin, market_controller, market_amm, fake_leverage, accounts):
    user = accounts[0]
    amount = 10 * 10**18
    leverage_method = get_method_id("leverage(address,uint256,uint256,uint256,uint256[])")  # min_amount for output collateral
    deleverage_method = get_method_id("deleverage(address,uint256,uint256,uint256,uint256[])")  # min_amount for stablecoins

    controller_mint = stablecoin.balanceOf(market_controller.address)

    with boa.env.prank(user):
        boa.env.set_balance(user, amount)
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
