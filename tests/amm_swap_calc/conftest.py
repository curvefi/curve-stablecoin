import boa
import pytest
from math import sqrt, log

PRICE = 3000


@pytest.fixture(scope="module")
def borrowed_token(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/ERC20Mock.vy', "Curve USD", "crvUSD", 18)


@pytest.fixture(scope="module")
def amm(collateral_token, borrowed_token, price_oracle, admin, accounts):
    with boa.env.prank(admin):
        amm = boa.load('contracts/AMM.vy',
                       borrowed_token.address, 10**(18 - borrowed_token.decimals()),
                       collateral_token.address, 10**(18 - collateral_token.decimals()),
                       100, int(sqrt(100/99) * 1e18), int(log(100/99) * 1e18),
                       PRICE * 10**18, 10**16, 0,
                       price_oracle.address)
        amm.set_admin(admin)
    for acct in accounts:
        with boa.env.prank(acct):
            collateral_token.approve(amm.address, 2**256-1)
            borrowed_token.approve(amm.address, 2**256-1)
    return amm


@pytest.fixture(scope="module")
def swap_calc(admin, collateral_token, borrowed_token, accounts):
    with boa.env.prank(admin):
        swap_calc = boa.load('contracts/SwapCalc.vy')
    for acct in accounts:
        with boa.env.prank(acct):
            collateral_token.approve(swap_calc.address, 2**256-1)
            borrowed_token.approve(swap_calc.address, 2**256-1)
    return swap_calc
