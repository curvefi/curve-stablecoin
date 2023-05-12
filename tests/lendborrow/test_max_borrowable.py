import boa
from hypothesis import given, settings
from hypothesis import strategies as st
from ..conftest import approx


DEAD_SHARES = 1000


@given(
    collateral_amount=st.integers(min_value=100, max_value=10**20),
    n=st.integers(min_value=5, max_value=50))
@settings(max_examples=1000)
def test_max_borrowable(market_controller, collateral_amount, n):
    max_borrowable = market_controller.max_borrowable(collateral_amount, n)
    with boa.reverts():
        market_controller.calculate_debt_n1(collateral_amount, int(max_borrowable * 1.001) + 1, n)
    if max_borrowable == 0:
        return
    market_controller.calculate_debt_n1(collateral_amount, max_borrowable, n)

    min_collateral = market_controller.min_collateral(max_borrowable, n)
    assert approx(min_collateral, collateral_amount, 1e-6 + (n**2 + n * DEAD_SHARES) / min(min_collateral, collateral_amount))


@given(
    debt_amount=st.integers(min_value=100, max_value=10**20),
    n=st.integers(min_value=5, max_value=50))
@settings(max_examples=1000)
def test_min_collateral(market_controller, debt_amount, n):
    min_collateral = market_controller.min_collateral(debt_amount, n)
    market_controller.calculate_debt_n1(min_collateral, debt_amount, n)
