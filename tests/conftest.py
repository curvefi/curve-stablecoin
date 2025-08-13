import os
from datetime import timedelta
from math import log
from typing import Any, Callable

import boa
import pytest
from hypothesis import settings
from tests.utils.deployers import ERC20_MOCK_DEPLOYER, DUMMY_PRICE_ORACLE_DEPLOYER


boa.env.enable_fast_mode()


PRICE = 3000


settings.register_profile("default", deadline=timedelta(seconds=1000))
settings.load_profile(os.getenv(u"HYPOTHESIS_PROFILE", "default"))


def approx(x1: float, x2: float, precision: float, abs_precision=None):
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
def accounts():
    return [boa.env.generate_address() for _ in range(10)]


@pytest.fixture(scope="session")
def admin():
    return boa.env.generate_address()


@pytest.fixture(scope="session")
def token_mock():
    return ERC20_MOCK_DEPLOYER


@pytest.fixture(scope="session")
def get_collateral_token(token_mock, admin) -> Callable[[int], Any]:
    def f(digits):
        with boa.env.prank(admin):
            return token_mock.deploy(digits)
    return f


@pytest.fixture(scope="session")
def get_borrowed_token(token_mock, admin) -> Callable[[int], Any]:
    def f(digits):
        with boa.env.prank(admin):
            return token_mock.deploy(digits)
    return f


@pytest.fixture(scope="session")
def collateral_token(get_collateral_token):
    return get_collateral_token(18)


@pytest.fixture(scope="session")
def price_oracle(admin):
    with boa.env.prank(admin):
        oracle = DUMMY_PRICE_ORACLE_DEPLOYER.deploy(admin, PRICE * 10**18)
        return oracle
