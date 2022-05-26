from brownie.test import given, strategy


@given(
    n=strategy('int256', min_value=5, max_value=50),
    debt=strategy('uint256', min_value=10**6, max_value=2 * 10**6 * 10**18),
    collateral=strategy('uint256', min_value=10**6, max_value=10**9 * 10**18 // 3000),
)
def test_n1(market_amm, market_controller, collateral, debt, n):
    n0 = market_amm.active_band()
    A = market_amm.A()
    p0 = market_amm.p_oracle_down(n0) / 1e18
    discounted_collateral = collateral * (10**18 - market_controller.loan_discount()) // 10**18

    too_high = False
    try:
        n1 = market_controller.calculate_debt_n1(collateral, debt, n)
    except Exception as e:
        too_high = str(e) == 'revert: Debt too high'
        if not too_high:
            raise
    if too_high:
        assert discounted_collateral * p0 * ((A - 1) / A)**n <= debt
        return

    assert discounted_collateral * p0 >= debt

    n2 = n1 + n - 1

    assert discounted_collateral * market_amm.p_oracle_up(n1) / 1e18 >= debt
    if n2 < 2500:
        assert discounted_collateral * market_amm.p_oracle_down(n2) / 1e18 <= debt
