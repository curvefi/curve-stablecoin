import os
from datetime import timedelta
from math import log
from typing import Any, Callable, List

import boa
import pytest
from boa.environment import AddressT
from hypothesis import settings

boa.interpret.set_cache_dir()
boa.reset_env()


PRICE = 3000


settings.register_profile("default", deadline=timedelta(seconds=1000))
settings.load_profile(os.getenv(u"HYPOTHESIS_PROFILE", "default"))


def approx(x1: int, x2: int, precision: float, abs_precision=None):
    if precision >= 1:
        return True
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
def accounts() -> List[AddressT]:
    return [boa.env.generate_address() for _ in range(10)]


@pytest.fixture(scope="session")
def admin() -> AddressT:
    return boa.env.generate_address()


@pytest.fixture(scope="session")
def get_collateral_token(admin) -> Callable[[int], Any]:
    def f(digits):
        with boa.env.prank(admin):
            return boa.load('contracts/testing/ERC20Mock.vy', "Colalteral", "ETH", digits)
    return f


@pytest.fixture(scope="session")
def get_borrowed_token(admin) -> Callable[[int], Any]:
    def f(digits):
        with boa.env.prank(admin):
            return boa.load('contracts/testing/ERC20Mock.vy', "Rugworks USD", "rUSD", digits)
    return f


@pytest.fixture(scope="module")
def collateral_token(get_collateral_token):
    return get_collateral_token(18)


@pytest.fixture(scope="module")
def price_oracle(admin):
    with boa.env.prank(admin):
        oracle = boa.load('contracts/testing/DummyPriceOracle.vy', admin, PRICE * 10**18)
        return oracle
