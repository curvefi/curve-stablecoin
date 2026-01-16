import boa
import pytest
from hypothesis import given, reproduce_failure
from hypothesis import strategies as st
from tests.utils import mint_for_testing
from tests.utils.deployers import ERC20_MOCK_DEPLOYER


@pytest.fixture(scope="module")
def borrowed_token():
    """Override borrowed_token to fix decimals at 18 for this module."""
    return ERC20_MOCK_DEPLOYER.deploy(18)


@pytest.fixture(scope="module")
def amm(get_amm, borrowed_token, collateral_token):
    return get_amm(collateral_token, borrowed_token)


@given(
    amounts=st.lists(st.floats(min_value=0.01, max_value=1e6), min_size=5, max_size=5),
    ns=st.lists(st.integers(min_value=1, max_value=20), min_size=5, max_size=5),
    dns=st.lists(st.integers(min_value=0, max_value=20), min_size=5, max_size=5),
)
def test_dydx_limits(
    amm, amounts, accounts, ns, dns, collateral_token, admin, borrowed_token
):
    collateral_decimals = collateral_token.decimals()
    borrowed_decimals = borrowed_token.decimals()
    amounts = list(map(lambda x: int(x * 10**collateral_decimals), amounts))

    with boa.env.prank(admin):
        for user, amount, n1, dn in zip(accounts[1:6], amounts, ns, dns):
            n2 = n1 + dn
            amm.deposit_range(user, amount, n1, n2)
            mint_for_testing(collateral_token, amm.address, amount)

    # Swap 0
    dx, dy = amm.get_dydx(0, 1, 0)
    assert dx == 0 and dy == 0
    dx, dy = amm.get_dydx(1, 0, 0)
    assert dx == dy == 0

    # Small swap
    small_y_amount = 10 ** (collateral_decimals - 6)  # 0.000001 ETH
    small_y_amount = max(1, small_y_amount)
    dy, dx = amm.get_dydx(0, 1, small_y_amount)
    assert dy == small_y_amount
    if min(ns) == 1:
        rel_precision = 4e-2 + 2 * min(ns) / amm.A()
        if dy == 1:
            rel_precision *= 2
        assert dx == pytest.approx(
            dy * 3000 / 10 ** (collateral_decimals - borrowed_decimals),
            rel=rel_precision,
        )
    else:
        assert dx >= dy * 3000 / 10 ** (collateral_decimals - borrowed_decimals)
    dy, dx = amm.get_dydx(1, 0, 10 ** (borrowed_decimals - 4))  # No liquidity
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
def test_dydx_compare_to_dxdy(
    amm, amounts, accounts, ns, dns, collateral_token, admin, borrowed_token
):
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
            mint_for_testing(collateral_token, amm.address, amount)

    # Swap 0
    dy, dx = amm.get_dydx(0, 1, 0)
    assert dx == dy == 0
    dy, dx = amm.get_dydx(1, 0, 0)
    assert dx == dy == 0

    # Small swap
    dy1, dx1 = amm.get_dydx(0, 1, 10 ** (collateral_decimals - 2))
    dx2, dy2 = amm.get_dxdy(0, 1, dx1)
    assert dx1 == dx2
    if dy1 == 1 or dy2 == 1:
        assert abs(dy1 - dy2) <= 1
    else:
        assert abs(dy1 - dy2) <= collateral_precision

    # Small swap
    small_x_amount = amm.price_oracle() // 10 ** (
        18 + collateral_decimals - borrowed_decimals
    )
    # 100 for 18 decimals, small_x_amount * 15 // 10 for 2 decimals
    small_x_amount = max(100, small_x_amount * 15 // 10)
    dx1, dy1 = amm.get_dxdy(0, 1, small_x_amount)
    dy2, dx2 = amm.get_dydx(0, 1, dy1)
    if dy1 == 1 or dy2 == 1:
        assert dx1 == pytest.approx(dx2, rel=0.5)
    else:
        assert abs(dx1 - dx2) <= borrowed_precision
    assert dy1 == dy2

    dy, dx = amm.get_dydx(1, 0, 10 ** (collateral_decimals - 2))  # No liquidity
    assert dx == 0
    assert dy == 0  # Rounded down

    # Huge swap
    dy1, dx1 = amm.get_dydx(0, 1, 10**12 * 10**collateral_decimals)
    dx2, dy2 = amm.get_dxdy(0, 1, dx1)
    assert dy1 < 10**12 * 10**collateral_decimals  # Less than all is desired
    assert abs(dy1 - sum(amounts)) <= 1000  # but everything is bought
    assert dx1 == dx2
    assert dy2 <= dy1  # We might get less because AMM rounds in its favor
    assert abs(dy1 - dy2) <= collateral_precision

    dx1, dy1 = amm.get_dxdy(0, 1, 10**12 * 10**borrowed_decimals)
    dy2, dx2 = amm.get_dydx(0, 1, dy1)
    assert dx1 < 10**12 * 10**borrowed_decimals  # Less than all is spent
    assert abs(dy1 - sum(amounts)) <= 1000  # but everything is bought
    assert dx1 == dx2
    assert dy1 == dy2

    dy, dx = amm.get_dydx(1, 0, 10**12 * 10**collateral_decimals)  # No liquidity
    assert dx == 0
    assert dy == 0  # Rounded down


@given(
    amounts=st.lists(st.floats(min_value=0.01, max_value=1e6), min_size=5, max_size=5),
    ns=st.lists(st.integers(min_value=1, max_value=20), min_size=5, max_size=5),
    dns=st.lists(st.integers(min_value=0, max_value=20), min_size=5, max_size=5),
    amount=st.floats(min_value=0.001, max_value=10e9),
)
def test_exchange_dy_down_up(
    amm, amounts, accounts, ns, dns, amount, borrowed_token, collateral_token, admin
):
    collateral_decimals = collateral_token.decimals()
    borrowed_decimals = borrowed_token.decimals()
    amounts = list(map(lambda x: int(x * 10**collateral_decimals), amounts))
    amount = int(amount * 10**borrowed_decimals)
    u = accounts[6]

    with boa.env.prank(admin):
        for user, amt, n1, dn in zip(accounts[1:6], amounts, ns, dns):
            n2 = n1 + dn
            if amt * 10 ** (18 - collateral_decimals) // (dn + 1) <= 100:
                with boa.reverts("Amount too low"):
                    amm.deposit_range(user, amt, n1, n2)
            else:
                amm.deposit_range(user, amt, n1, n2)
                mint_for_testing(collateral_token, amm.address, amt)

    p_before = amm.get_p()

    # crvUSD --> ETH (dx - crvUSD, dy - ETH)
    dy, dx = amm.get_dydx(0, 1, amount)
    assert dy <= amount
    dy2, dx2 = amm.get_dydx(0, 1, dy)
    assert dy == dy2
    assert dx == pytest.approx(dx2, rel=1e-6)
    mint_for_testing(borrowed_token, u, dx2)
    with boa.env.prank(u):
        with boa.reverts("Slippage"):
            amm.exchange_dy(0, 1, dy2, dx2 - 1)  # crvUSD --> ETH
        amm.exchange_dy(0, 1, dy2, dx2)  # crvUSD --> ETH
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

    # ETH --> crvUSD (dx - ETH, dy - crvUSD)
    expected_in_amount = dy2
    out_amount = dx2

    dy, dx = amm.get_dydx(1, 0, out_amount)
    assert dx >= expected_in_amount
    assert (
        abs(dx - expected_in_amount) <= 1
        or abs(dx - expected_in_amount) <= 2 * (fee + 0.01) * expected_in_amount
    )
    assert out_amount - dy <= 1

    mint_for_testing(collateral_token, u, dx - collateral_token.balanceOf(u))
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
