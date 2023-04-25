import boa
import pytest
from ..conftest import approx
from hypothesis import given
from hypothesis import strategies as st


@pytest.fixture(scope="module")
def borrowed_token(get_borrowed_token):
    return get_borrowed_token(18)


@pytest.fixture(scope="module")
def amm(get_amm, borrowed_token, collateral_token):
    return get_amm(collateral_token, borrowed_token)


@given(
        amounts=st.lists(st.floats(min_value=0.01, max_value=1e6), min_size=5, max_size=5),
        ns=st.lists(st.integers(min_value=1, max_value=20), min_size=5, max_size=5),
        dns=st.lists(st.integers(min_value=0, max_value=20), min_size=5, max_size=5),
)
def test_dydx_limits(amm, amounts, accounts, ns, dns, collateral_token, admin, borrowed_token):
    collateral_decimals = collateral_token.decimals()
    borrowed_decimals = borrowed_token.decimals()
    amounts = list(map(lambda x: int(x * 10 ** collateral_decimals), amounts))

    with boa.env.prank(admin):
        for user, amount, n1, dn in zip(accounts[1:6], amounts, ns, dns):
            n2 = n1 + dn
            amm.deposit_range(user, amount, n1, n2)
            collateral_token._mint_for_testing(amm.address, amount)

    # Swap 0
    dx, dy = amm.get_dydx(0, 1, 0)
    assert dx == 0 and dy == 0
    dx, dy = amm.get_dydx(1, 0, 0)
    assert dx == dy == 0

    # Small swap
    dy, dx = amm.get_dydx(0, 1, 10**(collateral_decimals - 6))  # 0.000001 ETH
    assert dy == 10**12
    assert approx(dx, dy * 3000 / 10**(collateral_decimals - borrowed_decimals), 4e-2 + 2 * min(ns) / amm.A())
    dy, dx = amm.get_dydx(1, 0, 10**(borrowed_decimals - 4))  # No liquidity
    assert dx == 0
    assert dy == 0  # Rounded down

    # Huge swap
    dy, dx = amm.get_dydx(0, 1, 10**12 * 10**collateral_decimals)
    assert dy < 10**12 * 10**collateral_decimals  # Less than desired amount
    assert abs(dy - sum(amounts)) <= 1000  # but everything is bought
    dy, dx = amm.get_dydx(1, 0, 10**12 * 10**borrowed_decimals)
    assert dx == 0
    assert dy == 0  # Rounded down


@given(
        amounts=st.lists(st.floats(min_value=0.01, max_value=1e6), min_size=5, max_size=5),
        ns=st.lists(st.integers(min_value=1, max_value=20), min_size=5, max_size=5),
        dns=st.lists(st.integers(min_value=0, max_value=20), min_size=5, max_size=5),
)
def test_dydx_compare_to_dxdy(amm, amounts, accounts, ns, dns, collateral_token, admin, borrowed_token):
    collateral_decimals = collateral_token.decimals()
    borrowed_decimals = borrowed_token.decimals()
    amounts = list(map(lambda x: int(x * 10**collateral_decimals), amounts))

    # 18 - 10_000, 17 - 1000, 16 - 100, 15 - 10, <= 14 - 1
    borrowed_precision = 10 ** (max(borrowed_decimals - 14, 0))
    # >= 16 - 0; 15, 14 - 10; 13, 12 - 1000 ...
    # collateral_precision = 10 ** (max(15 - (borrowed_decimals // 2) * 2, 0)) if borrowed_decimals < 16 else 0
    collateral_precision = 10 ** (18 - borrowed_decimals)

    with boa.env.prank(admin):
        for user, amount, n1, dn in zip(accounts[1:6], amounts, ns, dns):
            n2 = n1 + dn
            amm.deposit_range(user, amount, n1, n2)
            collateral_token._mint_for_testing(amm.address, amount)

    # Swap 0
    dy, dx = amm.get_dydx(0, 1, 0)
    assert dx == dy == 0
    dy, dx = amm.get_dydx(1, 0, 0)
    assert dx == dy == 0

    # Small swap
    dy1, dx1 = amm.get_dydx(0, 1, 10**(collateral_decimals - 2))
    dx2, dy2 = amm.get_dxdy(0, 1, dx1)
    assert dx1 == dx2
    assert abs(dy1 - dy2) <= collateral_precision

    dx1, dy1 = amm.get_dxdy(0, 1, 10**(borrowed_decimals - 2))
    dy2, dx2 = amm.get_dydx(0, 1, dy1)
    assert abs(dx1 - dx2) <= borrowed_precision
    assert dy1 == dy2

    dy, dx = amm.get_dydx(1, 0, 10**(collateral_decimals - 2))  # No liquidity
    assert dx == 0
    assert dy == 0  # Rounded down

    # Huge swap
    dy1, dx1 = amm.get_dydx(0, 1, 10**12 * 10**collateral_decimals)
    dx2, dy2 = amm.get_dxdy(0, 1, dx1)
    assert dy1 < 10**12 * 10**collateral_decimals      # Less than all is desired
    assert abs(dy1 - sum(amounts)) <= 1000             # but everything is bought
    assert dx1 == dx2
    assert dy2 <= dy1  # We might get less because AMM rounds in its favor
    assert abs(dy1 - dy2) <= collateral_precision

    dx1, dy1 = amm.get_dxdy(0, 1, 10**12 * 10**borrowed_decimals)
    dy2, dx2 = amm.get_dydx(0, 1, dy1)
    assert dx1 < 10**12 * 10**borrowed_decimals        # Less than all is spent
    assert abs(dy1 - sum(amounts)) <= 1000             # but everything is bought
    assert dx1 == dx2
    assert dy1 == dy2

    dy, dx = amm.get_dydx(1, 0, 10**12 * 10**collateral_decimals)  # No liquidity
    assert dx == 0
    assert dy == 0  # Rounded down


@given(
        amounts=st.lists(st.floats(min_value=0.01, max_value=1e6), min_size=5, max_size=5),
        ns=st.lists(st.integers(min_value=1, max_value=20), min_size=5, max_size=5),
        dns=st.lists(st.integers(min_value=0, max_value=20), min_size=5, max_size=5),
        amount=st.floats(min_value=0, max_value=10e9)
)
def test_exchange_dy_down_up(amm, amounts, accounts, ns, dns, amount, borrowed_token, collateral_token, admin):
    collateral_decimals = collateral_token.decimals()
    borrowed_decimals = borrowed_token.decimals()
    amounts = list(map(lambda x: int(x * 10**collateral_decimals), amounts))
    amount = amount * 10**borrowed_decimals
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

    # crvUSD --> ETH (dx - crvUSD, dy - ETH)
    dy, dx = amm.get_dydx(0, 1, amount)
    assert dy <= amount
    dy2, dx2 = amm.get_dydx(0, 1, dy)
    assert dy == dy2
    assert approx(dx, dx2, 1e-6)
    borrowed_token._mint_for_testing(u, dx2)
    with boa.env.prank(u):
        with boa.reverts("Slippage"):
            amm.exchange_dy(0, 1, dy2, dx2 - 1)  # crvUSD --> ETH
        amm.exchange_dy(0, 1, dy2, dx2)  # crvUSD --> ETH
    assert borrowed_token.balanceOf(u) == 0
    assert collateral_token.balanceOf(u) == dy2

    sum_borrowed = sum(amm.bands_x(i) for i in range(50))
    sum_collateral = sum(amm.bands_y(i) for i in range(50))
    assert abs(borrowed_token.balanceOf(amm) - sum_borrowed // 10**(18 - borrowed_decimals)) <= 1
    assert abs(collateral_token.balanceOf(amm) - sum_collateral // 10**(18 - collateral_decimals)) <= 1

    # ETH --> crvUSD (dx - ETH, dy - crvUSD)
    expected_in_amount = int(dy2 / 0.98)  # two trades charge 1% twice
    out_amount = dx2

    dy, dx = amm.get_dydx(1, 0, out_amount)
    assert approx(dx, expected_in_amount, 5e-4)  # Not precise because fee is charged on different directions
    assert out_amount - dy <= 1

    collateral_token._mint_for_testing(u, dx - collateral_token.balanceOf(u))
    dy_measured = borrowed_token.balanceOf(u)
    dx_measured = collateral_token.balanceOf(u)
    with boa.env.prank(u):
        with boa.reverts("Slippage"):
            amm.exchange_dy(1, 0, out_amount, dx - 1)  # ETH --> crvUSD
        amm.exchange_dy(1, 0, out_amount, dx)  # ETH --> crvUSD
    dy_measured = borrowed_token.balanceOf(u) - dy_measured
    dx_measured -= collateral_token.balanceOf(u)
    assert dy_measured == dy
    assert dx_measured == dx
