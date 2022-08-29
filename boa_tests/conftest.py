import boa
import pytest
from math import log

boa.interpret.set_cache_dir()


PRICE = 3000


def approx(x1, x2, precision, abs_precision=None):
    result = False
    if abs_precision is not None:
        result = abs(x2 - x1) <= abs_precision
    if x2 == 0:
        return x1 == 0
    elif x1 == 0:
        return x2 == 0
    return result or (abs(log(x1 / x2)) <= precision)


@pytest.fixture(scope="session")
def accounts():
    return [boa.env.generate_address() for i in range(10)]


@pytest.fixture(scope="session")
def admin():
    return boa.env.generate_address()


@pytest.fixture(scope="session")
def collateral_token(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/ERC20Mock.vy', "Colalteral", "ETH", 18)


@pytest.fixture(scope="session")
def price_oracle(admin):
    with boa.env.prank(admin):
        oracle = boa.load('contracts/testing/DummyPriceOracle.vy', admin, PRICE * 10**18)
        return oracle
