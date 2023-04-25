import boa
from ..conftest import approx
from hypothesis import given
from hypothesis import strategies as st


@given(
        amounts=st.lists(st.integers(min_value=10**16, max_value=10**6 * 10**18), min_size=5, max_size=5),
        ns=st.lists(st.integers(min_value=1, max_value=20), min_size=5, max_size=5),
        dns=st.lists(st.integers(min_value=0, max_value=20), min_size=5, max_size=5),
)
def test_dxdy_limits(amm, amounts, accounts, ns, dns, collateral_token, admin):
    with boa.env.prank(admin):
        for user, amount, n1, dn in zip(accounts[1:6], amounts, ns, dns):
            n2 = n1 + dn
            amm.deposit_range(user, amount, n1, n2)
            collateral_token._mint_for_testing(amm.address, amount)

    # Swap 0
    dx, dy = amm.get_dxdy(0, 1, 0)
    assert dx == 0 and dy == 0
    dx, dy = amm.get_dxdy(1, 0, 0)
    assert dx == dy == 0

    # Small swap
    dx, dy = amm.get_dxdy(0, 1, 10**2)  # $0.0001
    assert dx == 10**2
    assert approx(dy, dx * 10**(18 - 6) / 3000, 4e-2 + 2 * min(ns) / amm.A())
    dx, dy = amm.get_dxdy(1, 0, 10**16)  # No liquidity
    assert dx == 0
    assert dy == 0  # Rounded down

    # Huge swap
    dx, dy = amm.get_dxdy(0, 1, 10**12 * 10**6)
    assert dx < 10**12 * 10**6               # Less than all is spent
    assert abs(dy - sum(amounts)) <= 1000    # but everything is bought
    dx, dy = amm.get_dxdy(1, 0, 10**12 * 10**18)
    assert dx == 0
    assert dy == 0  # Rounded down


@given(
        amounts=st.lists(st.integers(min_value=10**16, max_value=10**6 * 10**18), min_size=5, max_size=5),
        ns=st.lists(st.integers(min_value=1, max_value=20), min_size=5, max_size=5),
        dns=st.lists(st.integers(min_value=0, max_value=20), min_size=5, max_size=5),
        amount=st.integers(min_value=0, max_value=10**9 * 10**6)
)
def test_exchange_down_up(amm, amounts, accounts, ns, dns, amount,
                          borrowed_token, collateral_token, admin):
    u = accounts[6]

    with boa.env.prank(admin):
        for user, amount, n1, dn in zip(accounts[1:6], amounts, ns, dns):
            n2 = n1 + dn
            if amount // (dn + 1) <= 100:
                with boa.reverts("Amount too low"):
                    amm.deposit_range(user, amount, n1, n2)
            else:
                amm.deposit_range(user, amount, n1, n2)
                collateral_token._mint_for_testing(amm.address, amount)

    dx, dy = amm.get_dxdy(0, 1, amount)
    assert dx <= amount
    dx2, dy2 = amm.get_dxdy(0, 1, dx)
    assert dx == dx2
    assert approx(dy, dy2, 1e-6)
    borrowed_token._mint_for_testing(u, dx2)
    with boa.env.prank(u):
        amm.exchange(0, 1, dx2, 0)
    assert borrowed_token.balanceOf(u) == 0
    assert collateral_token.balanceOf(u) == dy2

    sum_borrowed = sum(amm.bands_x(i) for i in range(50))
    sum_collateral = sum(amm.bands_y(i) for i in range(50))
    assert abs(borrowed_token.balanceOf(amm) - sum_borrowed // 10**(18 - 6)) <= 1
    assert abs(collateral_token.balanceOf(amm) - sum_collateral) <= 1

    in_amount = int(dy2 / 0.98)  # two trades charge 1% twice
    expected_out_amount = dx2

    dx, dy = amm.get_dxdy(1, 0, in_amount)
    assert approx(dx, in_amount, 5e-4)  # Not precise because fee is charged on different directions
    assert abs(dy - expected_out_amount) <= 1

    collateral_token._mint_for_testing(u, dx - collateral_token.balanceOf(u))
    dy_measured = borrowed_token.balanceOf(u)
    dx_measured = collateral_token.balanceOf(u)
    with boa.env.prank(u):
        amm.exchange(1, 0, in_amount, 0)
    dy_measured = borrowed_token.balanceOf(u) - dy_measured
    dx_measured -= collateral_token.balanceOf(u)
    assert dy == dy_measured
    assert dx == dx_measured
