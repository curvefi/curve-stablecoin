import boa
import pytest
from hypothesis import given
from hypothesis import strategies as st
from tests.utils import mint_for_testing


@given(
    collateral_amounts=st.lists(
        st.floats(min_value=0.01, max_value=1e6), min_size=5, max_size=5
    ),
    ns=st.lists(st.integers(min_value=1, max_value=20), min_size=5, max_size=5),
    dns=st.lists(st.integers(min_value=0, max_value=20), min_size=5, max_size=5),
)
def test_dxdy_limits(
    amm, collateral_amounts, accounts, ns, dns, collateral_token, borrowed_token, admin
):
    collateral_decimals = collateral_token.decimals()
    borrowed_decimals = borrowed_token.decimals()
    collateral_amounts = list(
        map(lambda x: int(x * 10**collateral_decimals), collateral_amounts)
    )

    with boa.env.prank(admin):
        for user, amount, n1, dn in zip(accounts[1:6], collateral_amounts, ns, dns):
            n2 = n1 + dn
            amm.deposit_range(user, amount, n1, n2)
            mint_for_testing(collateral_token, amm.address, amount)

    # Swap 0
    dx, dy = amm.get_dxdy(0, 1, 0)
    assert dx == 0 and dy == 0
    dx, dy = amm.get_dxdy(1, 0, 0)
    assert dx == dy == 0

    # Small swap
    small_x_amount = amm.price_oracle() // 10 ** (
        18 + collateral_decimals - borrowed_decimals
    )
    # 100 for 18 decimals, small_x_amount * 15 // 10 for 2 decimals
    small_x_amount = max(100, small_x_amount * 15 // 10)
    dx, dy = amm.get_dxdy(0, 1, small_x_amount)
    assert dy > 0
    assert dx == small_x_amount
    if min(ns) == 1:
        if collateral_decimals == 2:
            assert dy == int(
                dx * 10 ** (collateral_decimals - borrowed_decimals) / 3000
            )
        else:
            assert dy == pytest.approx(
                dx * 10 ** (collateral_decimals - borrowed_decimals) / 3000,
                rel=4e-2 + 2 * min(ns) / amm.A(),
            )
    else:
        assert dy <= dx * 10 ** (collateral_decimals - borrowed_decimals) / 3000
    dx, dy = amm.get_dxdy(1, 0, 10**16)  # No liquidity
    assert dx == 0
    assert dy == 0  # Rounded down

    # Huge swap
    dx, dy = amm.get_dxdy(0, 1, 10**12 * 10**borrowed_decimals)
    assert dx < 10**12 * 10**borrowed_decimals  # Less than all is spent
    assert abs(dy - sum(collateral_amounts)) <= 1000  # but everything is bought
    dx, dy = amm.get_dxdy(1, 0, 10**12 * 10**18)
    assert dx == 0
    assert dy == 0  # Rounded down


@given(
    collateral_amounts=st.lists(
        st.floats(min_value=0.01, max_value=1e6), min_size=5, max_size=5
    ),
    ns=st.lists(st.integers(min_value=1, max_value=20), min_size=5, max_size=5),
    dns=st.lists(st.integers(min_value=0, max_value=20), min_size=5, max_size=5),
    borrowed_amount=st.floats(min_value=0.001, max_value=10e9),
)
def test_exchange_down_up(
    amm,
    collateral_amounts,
    accounts,
    ns,
    dns,
    borrowed_amount,
    borrowed_token,
    collateral_token,
    admin,
):
    collateral_decimals = collateral_token.decimals()
    borrowed_decimals = borrowed_token.decimals()
    collateral_amounts = list(
        map(lambda x: int(x * 10**collateral_decimals), collateral_amounts)
    )
    borrowed_amount = int(borrowed_amount * 10**borrowed_decimals)
    borrowed_amount = max(
        borrowed_amount,
        amm.price_oracle() // 10 ** (18 + collateral_decimals - borrowed_decimals) * 2,
    )
    u = accounts[6]

    with boa.env.prank(admin):
        for user, amt, n1, dn in zip(accounts[1:6], collateral_amounts, ns, dns):
            n2 = n1 + dn
            if amt * 10 ** (18 - collateral_token.decimals()) // (dn + 1) <= 100:
                with boa.reverts("Amount too low"):
                    amm.deposit_range(user, amt, n1, n2)
            else:
                amm.deposit_range(user, amt, n1, n2)
                mint_for_testing(collateral_token, amm.address, amt)

    p_before = amm.get_p()

    dx, dy = amm.get_dxdy(0, 1, borrowed_amount)
    assert dx <= borrowed_amount
    dx2, dy2 = amm.get_dxdy(0, 1, dx)
    assert dx == dx2
    assert dy == pytest.approx(dy2, rel=1e-6)
    assert dy2 > 0
    mint_for_testing(borrowed_token, u, dx2)
    with boa.env.prank(u):
        amm.exchange(0, 1, dx2, 0)
    assert borrowed_token.balanceOf(u) == 0
    assert collateral_token.balanceOf(u) == dy2

    p_after = amm.get_p()
    fee = abs(p_after - p_before) / (4 * max(p_after, p_before))

    sum_borrowed = sum(amm.bands_x(i) for i in range(50))
    sum_collateral = sum(amm.bands_y(i) for i in range(50))
    assert (
        abs(
            borrowed_token.balanceOf(amm)
            - sum_borrowed // 10 ** (18 - borrowed_decimals)
        )
        <= 1
    )
    assert (
        abs(
            collateral_token.balanceOf(amm)
            - sum_collateral // 10 ** (18 - collateral_decimals)
        )
        <= 1
    )

    in_amount = int(dy2 / 0.98)  # two trades charge 1% twice
    expected_out_amount = dx2

    dx, dy = amm.get_dxdy(1, 0, in_amount)
    assert dx == pytest.approx(
        in_amount, rel=5e-4
    )  # Not precise because fee is charged on different directions
    assert dy <= expected_out_amount
    if dx == in_amount == 1:
        assert abs(dy - expected_out_amount) <= 2 * fee * expected_out_amount * 100
    else:
        assert abs(dy - expected_out_amount) <= 2 * fee * expected_out_amount

    mint_for_testing(collateral_token, u, dx - collateral_token.balanceOf(u))
    dy_measured = borrowed_token.balanceOf(u)
    dx_measured = collateral_token.balanceOf(u)
    with boa.env.prank(u):
        amm.exchange(1, 0, in_amount, 0)
    dy_measured = borrowed_token.balanceOf(u) - dy_measured
    dx_measured -= collateral_token.balanceOf(u)
    assert dy == dy_measured
    assert dx == dx_measured
