import boa
from ..conftest import approx
from hypothesis import given, settings
from hypothesis import strategies as st
from datetime import timedelta

@given(
        amounts=st.lists(st.integers(min_value=10**16, max_value=10**6 * 10**18), min_size=5, max_size=5),
        ns=st.lists(st.integers(min_value=1, max_value=20), min_size=5, max_size=5),
        dns=st.lists(st.integers(min_value=0, max_value=20), min_size=5, max_size=5),
)
@settings(deadline=timedelta(seconds=1000))
def test_dydx(amm, swap_calc, amounts, accounts, ns, dns, collateral_token, admin, borrowed_token):
    with boa.env.prank(admin):
        for user, amount, n1, dn in zip(accounts[1:6], amounts, ns, dns):
            n2 = n1 + dn
            collateral_token._mint_for_testing(user, amount)
            amm.deposit_range(user, amount, n1, n2, True)

    # Swap 0
    dy, dx = swap_calc.get_dydx(amm, 0, 1, 0)
    assert dx == 0 and dy == 0
    dy, dx = swap_calc.get_dydx(amm, 1, 0, 0)
    assert dx == dy == 0

    # Small swap
    dx1, dy1 = amm.get_dxdy(0, 1, 10**16)
    dy2, dx2 = swap_calc.get_dydx(amm, 0, 1, dy1)
    assert dy1 == dy2
    assert dx1 == dx2

    # dx1, dy1, n11, n21, ticks_in1, last_tick_j1, admin_fee1 = amm.get_swap_data(0, 1, 10**24)
    # dx2, dy2, n12, n22, ticks_in2, last_tick_j2, admin_fee2 = swap_calc.get_swap_data(amm, 0, 1, dy1)
    # assert n11 == n12
    # assert n21 == n22
    # assert last_tick_j1 == last_tick_j2
    # for n in range(n12, n22 + 1):
    #     assert ticks_in1[n] == ticks_in2[n]
    # assert admin_fee1 == admin_fee2
    # assert dy1 == dy2
    # assert dx1 == dx2

    # dx, dy = amm.get_dxdy(1, 0, 10**16)  # No liquidity
    # assert dx == 0
    # assert dy == 0  # Rounded down
    #
    # # Huge swap
    # dx, dy = amm.get_dxdy(0, 1, 10**12 * 10**6)
    # assert dx < 10**12 * 10**6               # Less than all is spent
    # assert abs(dy - sum(amounts)) <= 1000    # but everything is bought
    # dx, dy = amm.get_dxdy(1, 0, 10**12 * 10**18)
    # assert dx == 0
    # assert dy == 0  # Rounded down
