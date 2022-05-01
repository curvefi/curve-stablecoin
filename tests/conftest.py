import pytest
from math import log

PRICE = 3000


def approx(x1, x2, precision, abs_precision=None):
    result = False
    if abs_precision is not None:
        result = abs(x2 - x1) <= abs_precision
    if x2 == 0:
        return x1 == 0
    return result or (abs(log(x1 / x2)) <= precision)


@pytest.fixture(scope="module", autouse=True)
def PriceOracle(DummyPriceOracle, accounts):
    return DummyPriceOracle.deploy(accounts[0], PRICE * 10**18, {'from': accounts[0]})


@pytest.fixture(scope="module", autouse=True)
def ema_price_oracle(PriceOracle, EmaPriceOracle, accounts):
    return EmaPriceOracle.deploy(10000, PriceOracle, PriceOracle.price.signature, {'from': accounts[0]})


@pytest.fixture(scope="module", autouse=True)
def collateral_token(ERC20Mock, accounts):
    return ERC20Mock.deploy("Colalteral", "ETH", 18, {'from': accounts[0]})


@pytest.fixture(scope="module", autouse=True)
def borrowed_token(ERC20Mock, accounts):
    return ERC20Mock.deploy("Brrr", "USD", 6, {'from': accounts[0]})


@pytest.fixture(autouse=True)
def isolate(fn_isolation):
    pass
