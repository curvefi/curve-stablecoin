import boa
from hypothesis import given, settings
from hypothesis import strategies as st
from datetime import timedelta

@given(
        amounts=st.lists(st.integers(min_value=10**16, max_value=10**6 * 10**18), min_size=5, max_size=5),
        ns=st.lists(st.integers(min_value=1, max_value=20), min_size=5, max_size=5),
        dns=st.lists(st.integers(min_value=0, max_value=20), min_size=5, max_size=5),
)
@settings(deadline=timedelta(seconds=1000))
def test_dydx_limits(amm, swap_calc, amounts, accounts, ns, dns, collateral_token, admin, borrowed_token):
    with boa.env.prank(admin):
        for user, amount, n1, dn in zip(accounts[1:6], amounts, ns, dns):
            n2 = n1 + dn
            collateral_token._mint_for_testing(user, amount)
            amm.deposit_range(user, amount, n1, n2, True)

    # Swap 0
    dy, dx = swap_calc.get_dydx(amm, 0, 1, 0)
    assert dx == dy == 0
    dy, dx = swap_calc.get_dydx(amm, 1, 0, 0)
    assert dx == dy == 0

    dx_precision = 10**(max(borrowed_token.decimals() - 14, 0))  # 18 - 10_000, 17 - 1000, 16 - 100, 15 - 10, < 14 - 1
    print(dx_precision)

    # Small swap
    dx1, dy1 = amm.get_dxdy(0, 1, 10**16)
    dy2, dx2 = swap_calc.get_dydx(amm, 0, 1, dy1)
    assert dy1 == dy2
    assert abs(dx1 - dx2) <= dx_precision
    dy, dx = swap_calc.get_dydx(amm, 1, 0, 10**16)  # No liquidity
    assert dy == 0
    assert dx == 0  # Rounded down

    # Huge swap
    dy1, dx1 = swap_calc.get_dydx(amm, 0, 1, 10**12 * 10**18)
    dx2, dy2 = amm.get_dxdy(0, 1, dx1)
    assert dy1 < 10**12 * 10**18               # Less than all is desired
    assert abs(dy1 - sum(amounts)) <= 1000     # but everything is bought
    assert dy1 == dy2
    assert abs(dx1 - dx2) <= dx_precision
    dy, dx = swap_calc.get_dydx(amm, 1, 0, 10**12 * 10**18)  # No liquidity
    assert dy == 0
    assert dx == 0  # Rounded down
