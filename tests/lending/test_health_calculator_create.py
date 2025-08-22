import boa
from hypothesis import given
from hypothesis import strategies as st


@given(
    n=st.integers(min_value=5, max_value=50),
    debt=st.integers(min_value=10**10, max_value=2 * 10**6 * 10**18),
    collateral=st.integers(min_value=10**10, max_value=10**9 * 10**18 // 3000),
)
def test_health_calculator_create(market_amm, filled_controller, collateral_token, collateral, debt, n, accounts):
    collateral = collateral // 10**(18 - collateral_token.decimals())
    user = accounts[1]
    calculator_fail = False
    try:
        health = filled_controller.health_calculator(user, collateral, debt, False, n)
        health_full = filled_controller.health_calculator(user, collateral, debt, True, n)
    except Exception:
        calculator_fail = True

    boa.deal(collateral_token, user, collateral)

    with boa.env.prank(user):
        try:
            filled_controller.create_loan(collateral, debt, n)
        except Exception:
            return
    assert not calculator_fail

    assert abs(filled_controller.health(user) - health) / 1e18 < n * 2e-5
    assert abs(filled_controller.health(user, True) - health_full) / 1e18 < n * 2e-5
