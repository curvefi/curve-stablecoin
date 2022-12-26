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

    collateral_deciamls = collateral_token.decimals()
    borrowed_deciamls = borrowed_token.decimals()
    dx_precision = 10**(max(borrowed_deciamls - 14, 0))  # 18 - 10_000, 17 - 1000, 16 - 100, 15 - 10, < 14 - 1

    # Small swap
    dy1, dx1 = swap_calc.get_dydx(amm, 0, 1, 10**(collateral_deciamls - 2))
    dx2, dy2 = amm.get_dxdy(0, 1, dx1)
    assert dx1 == dx2
    assert dy1 == dy2

    dx1, dy1 = amm.get_dxdy(0, 1, 10**(borrowed_deciamls - 2))
    dy2, dx2 = swap_calc.get_dydx(amm, 0, 1, dy1)
    dx3, dy3 = amm.get_dxdy(0, 1, dx2)
    assert abs(dx1 - dx2) < dx_precision
    assert dx2 == dx3
    assert dy1 == dy2 == dy3

    dy, dx = swap_calc.get_dydx(amm, 1, 0, 10**(collateral_deciamls - 2))  # No liquidity
    assert dx == 0
    assert dy == 0  # Rounded down

    # Huge swap
    dy1, dx1 = swap_calc.get_dydx(amm, 0, 1, 10**12 * 10**collateral_deciamls)
    dx2, dy2 = amm.get_dxdy(0, 1, dx1)
    assert dy1 < 10**12 * 10**collateral_deciamls      # Less than all is desired
    assert abs(dy1 - sum(amounts)) <= 1000             # but everything is bought
    assert dx1 == dx2
    assert dy1 == dy2

    dx1, dy1 = amm.get_dxdy(0, 1, 10**12 * 10**borrowed_deciamls)
    dy2, dx2 = swap_calc.get_dydx(amm, 0, 1, dy1)
    assert dx1 < 10**12 * 10**borrowed_deciamls        # Less than all is spent
    assert abs(dy1 - sum(amounts)) <= 1000             # but everything is bought
    assert dx1 == dx2
    assert dy1 == dy2

    dy, dx = swap_calc.get_dydx(amm, 1, 0, 10**12 * 10**collateral_deciamls)  # No liquidity
    assert dx == 0
    assert dy == 0  # Rounded down
