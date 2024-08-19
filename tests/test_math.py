import pytest
import boa
from math import log2, sqrt, exp, log
from hypothesis import given, settings
from hypothesis import strategies as st

SETTINGS = dict(max_examples=2000)


@pytest.fixture(scope="module")
def optimized_math(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/OptimizeMath.vy')


@given(st.integers(min_value=0, max_value=2**256-1))
@settings(**SETTINGS)
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
@settings(**SETTINGS)
def test_sqrt(optimized_math, x):
    if x > (2**256 - 1) // 10**18:
        with boa.reverts():
            optimized_math.original_sqrt(x)
        with boa.reverts():
            optimized_math.optimized_sqrt(x)
        return

    y1 = optimized_math.original_sqrt(x)
    y2 = optimized_math.optimized_sqrt(x)
    y = sqrt(x / 1e18)

    assert y1 == y2
    assert abs(y2 / 1e18 - y) <= max(1e-15, 1e-15 * y)


@given(st.integers(min_value=0, max_value=2**256-1))
@settings(**SETTINGS)
def test_halfpow(optimized_math, power):
    pow_int = optimized_math.halfpow(power) / 1e18
    pow_ideal = 0.5 ** (power / 1e18)
    assert abs(pow_int - pow_ideal) < max(5 * 1e10 / 1e18, 5e-16)


@given(st.integers(min_value=-2**255, max_value=2**254-1))
@settings(**SETTINGS)
def test_exp(optimized_math, power):
    if power >= 135305999368893231589:
        with boa.reverts("exp overflow"):
            optimized_math.optimized_exp(power)
    elif power <= -41446531673892821376:
        assert optimized_math.optimized_exp(power) == 0
    else:
        pow_int = optimized_math.optimized_exp(power)
        pow_ideal = int(exp(power / 1e18) * 1e18)
        assert abs(pow_int - pow_ideal) < max(1e8, pow_ideal * 1e-10)


@given(st.integers(min_value=0, max_value=2**256-1))
@settings(**SETTINGS)
def test_wad_ln(optimized_math, x):
    if x > 0 and x < 2**255:
        y_v = optimized_math.wad_ln(x)
    elif x >= 2**255:
        with boa.reverts():
            optimized_math.wad_ln(x)
        return
    else:
        with boa.reverts():
            optimized_math.wad_ln(x)
        y_v = 0
    if x > 0:
        y = log(x / 1e18)
    else:
        y = 0

    assert abs(y_v / 1e18 - y) <= max(1e-9, 1e-9 * (abs(y) + 1))
