import pytest
import brownie
from math import log2, sqrt
from brownie.test import given, strategy
from hypothesis import settings


@pytest.fixture(scope="module", autouse=True)
def optimized_math(OptimizeMath, accounts):
    return OptimizeMath.deploy({'from': accounts[0]})


@given(strategy('uint256'))
@settings(max_examples=500)
def test_log2(optimized_math, x):
    y1 = optimized_math.original_log2(x)
    y2 = optimized_math.optimized_log2(x)
    if x >= 10**18:
        y = log2(x / 1e18)
    else:
        y = 0

    assert y1 == y2
    assert abs(y2 / 1e18 - y) <= max(1e-10, 1e-10 * y)


@given(strategy('uint256'))
@settings(max_examples=500)
def test_sqrt(optimized_math, x):
    if x > (2**256 - 1) / 10**18:
        with brownie.reverts():
            optimized_math.original_sqrt(x)
        with brownie.reverts():
            optimized_math.optimized_sqrt(x)
        return

    y1 = optimized_math.original_sqrt(x)
    y2 = optimized_math.optimized_sqrt(x)
    y = sqrt(x / 1e18)

    assert y1 == y2
    assert abs(y2 / 1e18 - y) <= max(1e-15, 1e-15 * y)
