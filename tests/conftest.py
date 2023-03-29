import boa
import os
import pytest
from math import log
from hypothesis import settings
from datetime import timedelta

boa.interpret.set_cache_dir()
boa.reset_env()


PRICE = 3000


settings.register_profile("default", deadline=timedelta(seconds=1000))
settings.load_profile(os.getenv(u"HYPOTHESIS_PROFILE", "default"))


def approx(x1, x2, precision, abs_precision=None):
    result = False
    if abs_precision is not None:
        result = abs(x2 - x1) <= abs_precision
    else:
        abs_precision = 0
    if x2 == 0:
        return abs(x1) <= abs_precision
    elif x1 == 0:
        return abs(x2) <= abs_precision
    return result or (abs(log(x1 / x2)) <= precision)


@pytest.fixture(scope="session")
def accounts():
    return [boa.env.generate_address() for i in range(10)]


@pytest.fixture(scope="session")
def admin():
    return boa.env.generate_address()


@pytest.fixture(scope="session")
def get_collateral_token(admin):
    def f(digits):
        with boa.env.prank(admin):
            return boa.load('contracts/testing/ERC20Mock.vy', "Colalteral", "ETH", digits)
    return f


@pytest.fixture(scope="session")
def get_borrowed_token(admin):
    def f(digits):
        with boa.env.prank(admin):
            return boa.load('contracts/testing/ERC20Mock.vy', "Rugworks USD", "rUSD", digits)
    return f


@pytest.fixture(scope="session")
def collateral_token(get_collateral_token):
    return get_collateral_token(18)


@pytest.fixture(scope="session")
def price_oracle(admin):
    with boa.env.prank(admin):
        oracle = boa.load('contracts/testing/DummyPriceOracle.vy', admin, PRICE * 10**18)
        return oracle
