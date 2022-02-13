import pytest
from math import log

PRICE = 3000


def approx(x1, x2, precision):
    return abs(log(x1 / x2)) <= precision


@pytest.fixture(scope="module", autouse=True)
def PriceOracle(DummyPriceOracle, accounts):
    return DummyPriceOracle.deploy(accounts[0], PRICE * 10**18, {'from': accounts[0]})


@pytest.fixture(scope="module", autouse=True)
def collateral_token(ERC20Mock, accounts):
    return ERC20Mock.deploy("Colalteral", "ETH", 18, {'from': accounts[0]})


@pytest.fixture(scope="module", autouse=True)
def borrowed_token(ERC20Mock, accounts):
    return ERC20Mock.deploy("Brrr", "USD", 6, {'from': accounts[0]})


@pytest.fixture(scope="module", autouse=True)
def amm(AMM, PriceOracle, collateral_token, borrowed_token, accounts):
    amm = AMM.deploy(
        collateral_token, borrowed_token,
        100, PRICE * 10**18, 10**16,
        accounts[0],
        PriceOracle, PriceOracle.price.signature,
        {'from': accounts[0]})
    for acct in accounts[1:6]:
        collateral_token.approve(amm, 2**256-1, {'from': acct})
        borrowed_token.approve(amm, 2**256-1, {'from': acct})
    return amm
