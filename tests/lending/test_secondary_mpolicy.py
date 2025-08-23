import boa
import pytest
from hypothesis import given
from hypothesis import settings
from hypothesis import strategies as st
from tests.utils.deployers import (
    ERC20_MOCK_DEPLOYER,
    MOCK_FACTORY_DEPLOYER,
    MOCK_MARKET_DEPLOYER,
    MOCK_RATE_SETTER_DEPLOYER,
    SECONDARY_MONETARY_POLICY_DEPLOYER
)


MIN_UTIL = 10**16
MAX_UTIL = 99 * 10**16
MIN_LOW_RATIO = 10**16
MAX_HIGH_RATIO = 100 * 10**18

RATE0 = int(0.1 * 1e18 / 365 / 86400)


@pytest.fixture(scope="module")
def factory():
    return MOCK_FACTORY_DEPLOYER.deploy()


@pytest.fixture(scope="module")
def controller():
    return MOCK_MARKET_DEPLOYER.deploy()


@pytest.fixture(scope="module")
def amm():
    return MOCK_RATE_SETTER_DEPLOYER.deploy(RATE0)


@pytest.fixture(scope="module")
def borrowed_token():
    return ERC20_MOCK_DEPLOYER.deploy(18)


@pytest.fixture(scope="module")
def mp(factory, amm, borrowed_token):
    return SECONDARY_MONETARY_POLICY_DEPLOYER.deploy(factory, amm, borrowed_token,
                    int(0.85 * 1e18), int(0.5 * 1e18), int(3 * 1e18), 0)


@given(
    total_debt=st.integers(0, 10**30),
    balance=st.integers(0, 10**30),
    u_0=st.integers(0, 10**18),
    min_ratio=st.integers(10**15, 10**19),
    max_ratio=st.integers(10**15, 10**19),
    shift=st.integers(0, 101 * 10**18)
)
@settings(max_examples=10000)
def test_mp(mp, factory, controller, borrowed_token, amm, total_debt, balance, u_0, min_ratio, max_ratio, shift):
    if u_0 >= int(0.2e18) and u_0 <= int(0.98e18) and \
       min_ratio > int(1e17) and max_ratio < (10e17) and \
       min_ratio < int(0.9e18) and max_ratio > int(1.1e18) and\
       shift <= 100 * 10**18:
        # These parameters will certainly work
        mp.set_parameters(u_0, min_ratio, max_ratio, shift)
    else:
        # Some of other parameters will also work unless they hit hard limits
        try:
            mp.set_parameters(u_0, min_ratio, max_ratio, shift)
        except Exception:
            return
        assert u_0 >= MIN_UTIL and u_0 <= MAX_UTIL
        assert min_ratio >= MIN_LOW_RATIO and min_ratio <= 10**18
        assert max_ratio <= MAX_HIGH_RATIO and max_ratio >= 10**18

    controller.set_debt(total_debt)
    boa.deal(borrowed_token, controller.address, balance)

    rate = mp.rate(controller.address)

    assert rate >= RATE0 * min_ratio // 10**18 * 0.999999 + shift
    assert rate <= RATE0 * max_ratio // 10**18 * 1.000001 + shift

    mp.rate_write(controller.address)
