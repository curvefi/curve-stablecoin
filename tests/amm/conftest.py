import pytest
from ..conftest import PRICE


@pytest.fixture(scope="module", autouse=True)
def amm(AMM, PriceOracle, collateral_token, borrowed_token, accounts):
    # Instead of factory contract, we deploy manually
    amm = AMM.deploy(borrowed_token, {'from': accounts[0]})
    amm.initialize(100, PRICE * 10**18, collateral_token, 10**16, 0,
                   PriceOracle, accounts[0],
                   {'from': accounts[0]})
    for acct in accounts[1:7]:
        collateral_token.approve(amm, 2**256-1, {'from': acct})
        borrowed_token.approve(amm, 2**256-1, {'from': acct})
    return amm


@pytest.fixture(autouse=True)
def isolate(fn_isolation):
    pass
