import pytest
from brownie.test import given, strategy
from hypothesis import settings

MAX_N = 2**127 - 1
MIN_N = -2**127


@pytest.fixture(scope="module", autouse=True)
def packing(TestPacking, accounts):
    return TestPacking.deploy({'from': accounts[0]})


@given(
    n1=strategy('int256', min_value=MIN_N, max_value=MAX_N),
    n2=strategy('int256', min_value=MIN_N, max_value=MAX_N)
)
@settings(max_examples=500)
def test_packing(packing, n1, n2):
    n1, n2 = sorted([n1, n2])
    n1out, n2out = packing.unpack_ticks(packing.pack_ticks(n1, n2))
    assert n1out == n1
    assert n2out == n2
