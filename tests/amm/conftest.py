import pytest
from math import log, sqrt
from ..conftest import PRICE


@pytest.fixture(scope="module", autouse=True)
def amm(AMM, PriceOracle, collateral_token, borrowed_token, accounts):
    # Instead of factory contract, we deploy manually
    amm = AMM.deploy(
            borrowed_token, 10**(18 - borrowed_token.decimals()),
            collateral_token, 10**(18 - collateral_token.decimals()),
            100, int(sqrt(100/99) * 1e18), int(log(100/99) * 1e18),
            PRICE * 10**18, 10**16, 0, PriceOracle,
            {'from': accounts[0]})
    amm.set_admin(accounts[0], {'from': accounts[0]})
    for acct in accounts[1:7]:
        collateral_token.approve(amm, 2**256-1, {'from': acct})
        borrowed_token.approve(amm, 2**256-1, {'from': acct})
    return amm


@pytest.fixture(autouse=True)
def isolate(fn_isolation):
    pass
