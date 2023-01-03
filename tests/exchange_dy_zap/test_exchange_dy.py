import boa
from ..conftest import approx
from hypothesis import given, settings
from hypothesis import strategies as st
from datetime import timedelta


@given(
        amounts=st.lists(st.floats(min_value=0.01, max_value=1e6), min_size=5, max_size=5),
        ns=st.lists(st.integers(min_value=1, max_value=20), min_size=5, max_size=5),
        dns=st.lists(st.integers(min_value=0, max_value=20), min_size=5, max_size=5),
)
@settings(deadline=timedelta(seconds=1000))
def test_dydx_limits(amm, exchange_dy_zap, amounts, accounts, ns, dns, collateral_token, admin, borrowed_token):
    collateral_deciamls = collateral_token.decimals()
    borrowed_deciamls = borrowed_token.decimals()
    amounts = list(map(lambda x: int(x * 10**collateral_deciamls), amounts))

    # 18 - 10_000, 17 - 1000, 16 - 100, 15 - 10, <= 14 - 1
    borrowed_precision = 10 ** (max(borrowed_deciamls - 14, 0))
    # >= 16 - 0; 15, 14 - 10; 13, 12 - 1000 ...
    collateral_precision = 10 ** (max(15 - (borrowed_deciamls // 2) * 2, 0)) if borrowed_deciamls < 16 else 0

    with boa.env.prank(admin):
        for user, amount, n1, dn in zip(accounts[1:6], amounts, ns, dns):
            n2 = n1 + dn
            collateral_token._mint_for_testing(user, amount)
            amm.deposit_range(user, amount, n1, n2, True)

    # Swap 0
    dy, dx = exchange_dy_zap.get_dydx(amm, 0, 1, 0)
    assert dx == dy == 0
    dy, dx = exchange_dy_zap.get_dydx(amm, 1, 0, 0)
    assert dx == dy == 0

    # Small swap
    dy1, dx1 = exchange_dy_zap.get_dydx(amm, 0, 1, 10**(collateral_deciamls - 2))
    dx2, dy2 = amm.get_dxdy(0, 1, dx1)
    assert dx1 == dx2
    assert abs(dy1 - dy2) <= collateral_precision

    dx1, dy1 = amm.get_dxdy(0, 1, 10**(borrowed_deciamls - 2))
    dy2, dx2 = exchange_dy_zap.get_dydx(amm, 0, 1, dy1)
    assert abs(dx1 - dx2) <= borrowed_precision
    assert dy1 == dy2

    dy, dx = exchange_dy_zap.get_dydx(amm, 1, 0, 10**(collateral_deciamls - 2))  # No liquidity
    assert dx == 0
    assert dy == 0  # Rounded down

    # Huge swap
    dy1, dx1 = exchange_dy_zap.get_dydx(amm, 0, 1, 10**12 * 10**collateral_deciamls)
    dx2, dy2 = amm.get_dxdy(0, 1, dx1)
    assert dy1 < 10**12 * 10**collateral_deciamls      # Less than all is desired
    assert abs(dy1 - sum(amounts)) <= 1000             # but everything is bought
    assert dx1 == dx2
    assert dy1 == dy2

    dx1, dy1 = amm.get_dxdy(0, 1, 10**12 * 10**borrowed_deciamls)
    dy2, dx2 = exchange_dy_zap.get_dydx(amm, 0, 1, dy1)
    assert dx1 < 10**12 * 10**borrowed_deciamls        # Less than all is spent
    assert abs(dy1 - sum(amounts)) <= 1000             # but everything is bought
    assert dx1 == dx2
    assert dy1 == dy2

    dy, dx = exchange_dy_zap.get_dydx(amm, 1, 0, 10**12 * 10**collateral_deciamls)  # No liquidity
    assert dx == 0
    assert dy == 0  # Rounded down


@given(
        amounts=st.lists(st.floats(min_value=0.01, max_value=1e6), min_size=5, max_size=5),
        ns=st.lists(st.integers(min_value=1, max_value=20), min_size=5, max_size=5),
        dns=st.lists(st.integers(min_value=0, max_value=20), min_size=5, max_size=5),
        amount=st.floats(min_value=0, max_value=10e9)
)
@settings(deadline=timedelta(seconds=1000))
def test_exchange_dy_down_up(amm, exchange_dy_zap, amounts, accounts, ns, dns, amount, borrowed_token, collateral_token, admin):
    collateral_deciamls = collateral_token.decimals()
    borrowed_deciamls = borrowed_token.decimals()
    amounts = list(map(lambda x: int(x * 10**collateral_deciamls), amounts))
    amount = amount * 10**borrowed_deciamls
    u = accounts[6]

    # 18 - 10_000, 17 - 1000, 16 - 100, 15 - 10, <= 14 - 1
    borrowed_precision = 10 ** (max(borrowed_deciamls - 14, 0))
    # >= 16 - 0; 15, 14 - 10; 13, 12 - 1000 ...
    collateral_precision = 10 ** (max(15 - (borrowed_deciamls // 2) * 2, 0)) if borrowed_deciamls < 16 else 0

    with boa.env.prank(admin):
        for user, amount, n1, dn in zip(accounts[1:6], amounts, ns, dns):
            n2 = n1 + dn
            collateral_token._mint_for_testing(user, amount)
            if amount // (dn + 1) <= 100:
                with boa.reverts("Amount too low"):
                    amm.deposit_range(user, amount, n1, n2, True)
            else:
                amm.deposit_range(user, amount, n1, n2, True)

    dy, dx = exchange_dy_zap.get_dydx(amm, 0, 1, amount)
    assert dy <= amount
    dy2, dx2 = exchange_dy_zap.get_dydx(amm, 0, 1, dy)
    assert dy == dy2
    assert approx(dx, dx2, 1e-6)
    borrowed_token._mint_for_testing(u, dx2)
    with boa.env.prank(u):
        with boa.reverts("Slippage"):
            exchange_dy_zap.exchange_dy(amm, 0, 1, dy2, dx2 - 1)  # crvUSD --> ETH
        exchange_dy_zap.exchange_dy(amm, 0, 1, dy2, dx2)  # crvUSD --> ETH
    assert borrowed_token.balanceOf(u) == 0
    assert abs(collateral_token.balanceOf(u) - dy2) <= collateral_precision

    sum_borrowed = sum(amm.bands_x(i) for i in range(50))
    sum_collateral = sum(amm.bands_y(i) for i in range(50))
    assert abs(borrowed_token.balanceOf(amm) - sum_borrowed // 10**(18 - borrowed_deciamls)) <= 1
    assert abs(collateral_token.balanceOf(amm) - sum_collateral // 10**(18 - collateral_deciamls)) <= 1

    expected_in_amount = int(dy2 / 0.98)  # two trades charge 1% twice
    out_amount = dx2

    dy, dx = exchange_dy_zap.get_dydx(amm, 1, 0, out_amount)
    assert approx(dx, expected_in_amount, 5e-4)  # Not precise because fee is charged on different directions
    assert dy == out_amount

    collateral_token._mint_for_testing(u, dx - collateral_token.balanceOf(u))
    dy_measured = borrowed_token.balanceOf(u)
    dx_measured = collateral_token.balanceOf(u)
    with boa.env.prank(u):
        with boa.reverts("Slippage"):
            exchange_dy_zap.exchange_dy(amm, 1, 0, out_amount, dx - 1)  # ETH --> crvUSD
        exchange_dy_zap.exchange_dy(amm, 1, 0, out_amount, dx)  # ETH --> crvUSD
    dy_measured = borrowed_token.balanceOf(u) - dy_measured
    dx_measured -= collateral_token.balanceOf(u)
    assert abs(dy_measured - dy) <= borrowed_precision
    assert approx(dx_measured, dx, 5e-5)
