import boa
import pytest

PRICE = 3000


@pytest.fixture(scope="session")
def borrowed_token(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/ERC20Mock.vy', "Rugworks USD", "rUSD", 6)


@pytest.fixture(scope="session")
def amm(collateral_token, borrowed_token, price_oracle, admin, accounts):
    with boa.env.prank(admin):
        amm = boa.load('contracts/AMM.vy', borrowed_token.address)
        amm.initialize(100, PRICE * 10**18, collateral_token.address, 10**16, 0,
                       price_oracle.address, admin)
    for acct in accounts:
        with boa.env.prank(acct):
            collateral_token.approve(amm.address, 2**256-1)
            borrowed_token.approve(amm.address, 2**256-1)
    return amm
