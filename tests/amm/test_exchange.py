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
    amm,
    price_oracle,
    collateral_amounts,
    ns,
    dns,
    collateral_token,
    borrowed_token,
    admin,
):
    collateral_decimals = collateral_token.decimals()
    borrowed_decimals = borrowed_token.decimals()
    collateral_amounts = list(
        map(lambda x: int(x * 10**collateral_decimals), collateral_amounts)
    )
    depositors = [boa.env.generate_address() for _ in range(5)]

    with boa.env.prank(admin):
        for depositor, amount, n1, dn in zip(depositors, collateral_amounts, ns, dns):
            n2 = n1 + dn
            amm.deposit_range(depositor, amount, n1, n2)
            mint_for_testing(collateral_token, amm.address, amount)

    # Swap 0
    dx, dy = amm.get_dxdy(0, 1, 0)
    assert dx == 0 and dy == 0
    with boa.reverts("Wrong index"):
        amm.get_dxdy(1, 0, 0)

    # p_oracle is above the bands: nothing is sold
    dx, dy = amm.get_dxdy(0, 1, 10**12 * 10**borrowed_decimals)
    assert dx == 0 and dy == 0

    # p_oracle inside the first band: only its collateral is sold
    with boa.env.prank(admin):
        price_oracle.set_price(amm.p_oracle_down(min(ns)) + 1)
    boa.env.time_travel(600)  # To reset the prev p_o counter
    dx, dy = amm.get_dxdy(0, 1, 10**12 * 10**borrowed_decimals)
    assert dx > 0
    assert dy == amm.bands_y(min(ns)) // 10 ** (18 - collateral_decimals)

    # p_oracle at the bottom of the last band: all the bands are reached
    n_last = max(n1 + dn for n1, dn in zip(ns, dns))
    with boa.env.prank(admin):
        price_oracle.set_price(amm.p_oracle_down(n_last))
    boa.env.time_travel(600)  # To reset the prev p_o counter
    p_o = amm.price_oracle() / 1e18

    # Small swap
    small_x_amount = amm.price_oracle() // 10 ** (
        18 + collateral_decimals - borrowed_decimals
    )
    # 100 for 18 decimals, small_x_amount * 15 // 10 for 2 decimals
    small_x_amount = max(100, small_x_amount * 15 // 10)
    dx, dy = amm.get_dxdy(0, 1, small_x_amount)
    assert dy > 0
    assert dx == small_x_amount
    # Bands which p_oracle has passed are sold below it, the first band from its
    # p_current_down, with the dynamic fee or the AMM fee, whichever is larger
    p_min = amm.p_current_down(min(ns)) / 1e18
    fee = max(amm.fee() / 1e18, (1 - amm.p_current_up(min(ns)) / 1e18 / p_o) / 4)
    dy_precise = (
        dx * 10 ** (collateral_decimals - borrowed_decimals) / p_min * (1 - fee)
    )
    if amm.bands_y(min(ns)) >= 2 * dy * 10 ** (18 - collateral_decimals):
        if collateral_decimals == 2:
            assert int(dy_precise * (1 - 4e-2)) <= dy <= int(dy_precise * (1 + 1e-6))
        else:
            assert dy == pytest.approx(dy_precise, rel=4e-2)
    else:
        # The first band holds less than twice the swap: the next bands can be sold too
        assert dy <= dx * 10 ** (collateral_decimals - borrowed_decimals) / p_min
        assert dy >= int(
            dx * 10 ** (collateral_decimals - borrowed_decimals) / p_o * (1 - 4e-2)
        )
    with boa.reverts("Wrong index"):
        amm.get_dxdy(1, 0, 10**16)

    # Huge swap
    dx, dy = amm.get_dxdy(0, 1, 10**12 * 10**borrowed_decimals)
    assert dx < 10**12 * 10**borrowed_decimals  # Less than all is spent
    assert abs(dy - sum(collateral_amounts)) <= 1000  # but everything is bought
    with boa.reverts("Wrong index"):
        amm.get_dxdy(1, 0, 10**12 * 10**18)


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
    price_oracle,
    collateral_amounts,
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
    depositors = [boa.env.generate_address() for _ in range(5)]
    trader = boa.env.generate_address()
    with boa.env.prank(trader):
        borrowed_token.approve(amm.address, 2**256 - 1)
        collateral_token.approve(amm.address, 2**256 - 1)

    with boa.env.prank(admin):
        for depositor, amt, n1, dn in zip(depositors, collateral_amounts, ns, dns):
            n2 = n1 + dn
            if amt * 10 ** (18 - collateral_token.decimals()) // (dn + 1) <= 100:
                with boa.reverts("Amount too low"):
                    amm.deposit_range(depositor, amt, n1, n2)
            else:
                amm.deposit_range(depositor, amt, n1, n2)
                mint_for_testing(collateral_token, amm.address, amt)

    # p_oracle is above the bands: nothing is sold
    dx, dy = amm.get_dxdy(0, 1, borrowed_amount)
    assert dx == 0 and dy == 0
    mint_for_testing(borrowed_token, trader, borrowed_amount)
    with boa.env.prank(trader):
        amm.exchange(0, 1, borrowed_amount, 0)
    assert borrowed_token.balanceOf(trader) == borrowed_amount
    assert collateral_token.balanceOf(trader) == 0
    assert amm.active_band() == 0
    with boa.env.prank(trader):
        borrowed_token.transfer(admin, borrowed_amount)

    # p_oracle at the bottom of the last band: all the bands are reached
    with boa.env.prank(admin):
        price_oracle.set_price(
            amm.p_oracle_down(max(n1 + dn for n1, dn in zip(ns, dns)))
        )
    boa.env.time_travel(600)  # To reset the prev p_o counter

    p_before = amm.get_p()

    dx, dy = amm.get_dxdy(0, 1, borrowed_amount)
    assert dx <= borrowed_amount
    dx2, dy2 = amm.get_dxdy(0, 1, dx)
    assert dx == dx2
    assert dy == pytest.approx(dy2, rel=1e-6)
    assert dy2 > 0
    mint_for_testing(borrowed_token, trader, dx2)
    with boa.env.prank(trader):
        amm.exchange(0, 1, dx2, 0)
    assert borrowed_token.balanceOf(trader) == 0
    assert collateral_token.balanceOf(trader) == dy2

    p_after = amm.get_p()
    assert p_after > p_before  # A trade only moves the price up

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

    # Collateral is never bought back
    in_amount = int(dy2 / 0.98)
    with boa.reverts("Wrong index"):
        amm.get_dxdy(1, 0, in_amount)

    mint_for_testing(collateral_token, trader, in_amount - dy2)
    with boa.env.prank(trader):
        with boa.reverts("Wrong index"):
            amm.exchange(1, 0, in_amount, 0)
    assert borrowed_token.balanceOf(trader) == 0
    assert collateral_token.balanceOf(trader) == in_amount
    assert sum_borrowed == sum(amm.bands_x(i) for i in range(50))
    assert sum_collateral == sum(amm.bands_y(i) for i in range(50))
