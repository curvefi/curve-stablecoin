import boa
import pytest


@pytest.fixture(scope="module")
def fake_leverage(stablecoin, weth, market_controller, admin):
    with boa.env.prank(admin):
        leverage = boa.load('contracts/testing/FakeLeverage.vy', stablecoin.address, weth.address,
                            market_controller.address, 3000 * 10**18)
        boa.env.set_balance(admin, 1000 * 10**18)
        weth.deposit(value=1000 * 10**18)
        weth.transfer(leverage.address, 1000 * 10**18)


def test_leverage(weth, stablecoin, market_controller, fake_leverage, accounts):
    pass
