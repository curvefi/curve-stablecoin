import boa
import pytest
from hypothesis import strategies as st
from hypothesis import given, settings
from tests.utils.deployers import TEST_PACKING_DEPLOYER

MAX_N = 2**127 - 1
MIN_N = -2**127 + 1  # <- not -2**127!


@pytest.fixture(scope="module")
def packing(admin):
    with boa.env.prank(admin):
        return TEST_PACKING_DEPLOYER.deploy()


@given(
    n1=st.integers(min_value=MIN_N, max_value=MAX_N),
    n2=st.integers(min_value=MIN_N, max_value=MAX_N)
)
@settings(max_examples=500)
def test_packing(packing, n1, n2):
    n1, n2 = sorted([n1, n2])
    n1out, n2out = packing.unpack_ticks(packing.pack_ticks(n1, n2))
    assert n1out == n1
    assert n2out == n2
