import pytest
import boa
from math import log2, sqrt
from hypothesis import given, settings
from hypothesis import strategies as st
from boa.contract import BoaError
from datetime import timedelta


@pytest.fixture(scope="module")
def optimized_math(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/OptimizeMath.vy')


@given(st.integers(min_value=0, max_value=2**256-1))
@settings(max_examples=500, deadline=timedelta(seconds=1000))
def test_log2(optimized_math, x):
    y1 = optimized_math.original_log2(x)
    if x > 0:
        y2 = optimized_math.optimized_log2(x)
    else:
        with pytest.raises(Exception):
            optimized_math.optimized_log2(x)
        y2 = 0
    if x > 0:
        y = log2(x / 1e18)
    else:
        y = 0

    if x >= 10**18:
        assert y1 == y2
    else:
        assert y1 == 0
    assert abs(y2 / 1e18 - y) <= max(1e-9, 1e-9 * (abs(y) + 1))


@given(st.integers(min_value=0, max_value=2**256-1))
@settings(max_examples=500, deadline=timedelta(seconds=1000))
def test_sqrt(optimized_math, x):
    if x > (2**256 - 1) / 10**18:
        with pytest.raises(BoaError):
            optimized_math.original_sqrt(x)
        with pytest.raises(BoaError):
            optimized_math.optimized_sqrt(x)
        return

    y1 = optimized_math.original_sqrt(x)
    y2 = optimized_math.optimized_sqrt(x)
    y = sqrt(x / 1e18)

    assert y1 == y2
    assert abs(y2 / 1e18 - y) <= max(1e-15, 1e-15 * y)
