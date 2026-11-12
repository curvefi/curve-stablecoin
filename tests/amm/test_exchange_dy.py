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
    amm, price_oracle, amounts, ns, dns, collateral_token, admin, borrowed_token
):
    collateral_decimals = collateral_token.decimals()
    borrowed_decimals = borrowed_token.decimals()
    amounts = list(map(lambda x: int(x * 10**collateral_decimals), amounts))
    depositors = [boa.env.generate_address() for _ in range(5)]

    with boa.env.prank(admin):
        for depositor, amount, n1, dn in zip(depositors, amounts, ns, dns):
            n2 = n1 + dn
            amm.deposit_range(depositor, amount, n1, n2)
            mint_for_testing(collateral_token, amm.address, amount)

    # Swap 0
    dx, dy = amm.get_dydx(0, 1, 0)
    assert dx == 0 and dy == 0
    with boa.reverts("Wrong index"):
        amm.get_dydx(1, 0, 0)

    # p_oracle is above the bands: nothing is sold
    dy, dx = amm.get_dydx(0, 1, 10**12 * 10**collateral_decimals)
    assert dx == 0 and dy == 0

    # p_oracle inside the first band: only its collateral is sold
    with boa.env.prank(admin):
        price_oracle.set_price(amm.p_oracle_down(min(ns)) + 1)
    boa.env.time_travel(600)  # To reset the prev p_o counter
    dy, dx = amm.get_dydx(0, 1, 10**12 * 10**collateral_decimals)
    assert dx > 0
    assert dy == amm.bands_y(min(ns)) // 10 ** (18 - collateral_decimals)

    # p_oracle at the bottom of the last band: all the bands are reached
    n_last = max(n1 + dn for n1, dn in zip(ns, dns))
    with boa.env.prank(admin):
        price_oracle.set_price(amm.p_oracle_down(n_last))
    boa.env.time_travel(600)  # To reset the prev p_o counter
    p_o = amm.price_oracle() / 1e18

    # Small swap
    small_y_amount = 10 ** (collateral_decimals - 6)  # 0.000001 ETH
    small_y_amount = max(1, small_y_amount)
    dy, dx = amm.get_dydx(0, 1, small_y_amount)
    assert dy == small_y_amount
    # Bands which p_oracle has passed are sold below it, the first band from its
    # p_current_down, with the dynamic fee or the AMM fee, whichever is larger
    p_min = amm.p_current_down(min(ns)) / 1e18
    fee = max(amm.fee() / 1e18, (1 - amm.p_current_up(min(ns)) / 1e18 / p_o) / 4)
    if amm.bands_y(min(ns)) >= dy * 10 ** (18 - collateral_decimals):
        rel_precision = 4e-2
        if dy == 1:
            rel_precision *= 2
        assert dx == pytest.approx(
            dy * p_min / (1 - fee) / 10 ** (collateral_decimals - borrowed_decimals),
            rel=rel_precision,
        )
        # The price only goes up from p_current_down: never less is paid
        assert dx >= int(
            dy * p_min / (1 - fee) / 10 ** (collateral_decimals - borrowed_decimals)
        )
    else:
        # The first band holds less than the swap: the next bands are sold too
        assert dx >= dy * p_min / 10 ** (collateral_decimals - borrowed_decimals)
        assert dx <= dy * p_o / 10 ** (collateral_decimals - borrowed_decimals) * (
            1 + 4e-2
        )
    with boa.reverts("Wrong index"):
        amm.get_dydx(1, 0, 10 ** (borrowed_decimals - 4))

    # Huge swap
    dy, dx = amm.get_dydx(0, 1, 10**12 * 10**collateral_decimals)
    assert dy < 10**12 * 10**collateral_decimals  # Less than desired amount
    assert abs(dy - sum(amounts)) <= 1000  # but everything is bought
    with boa.reverts("Wrong index"):
        amm.get_dydx(1, 0, 10**12 * 10**borrowed_decimals)


@given(
    amounts=st.lists(st.floats(min_value=0.01, max_value=1e6), min_size=5, max_size=5),
    ns=st.lists(st.integers(min_value=1, max_value=20), min_size=5, max_size=5),
    dns=st.lists(st.integers(min_value=0, max_value=20), min_size=5, max_size=5),
)
def test_dydx_compare_to_dxdy(
    amm, price_oracle, amounts, ns, dns, collateral_token, admin, borrowed_token
):
    collateral_decimals = collateral_token.decimals()
    borrowed_decimals = borrowed_token.decimals()
    amounts = list(map(lambda x: int(x * 10**collateral_decimals), amounts))

    # 18 - 10_000, 17 - 1000, 16 - 100, 15 - 10, <= 14 - 1
    borrowed_precision = 10 ** (max(borrowed_decimals - 14, 0))
    # >= 16 - 0; 15, 14 - 10; 13, 12 - 1000 ...
    # collateral_precision = 10 ** (max(15 - (borrowed_decimals // 2) * 2, 0)) if borrowed_decimals < 16 else 0
    collateral_precision = 10 ** (18 - borrowed_decimals)
    depositors = [boa.env.generate_address() for _ in range(5)]

    with boa.env.prank(admin):
        for depositor, amount, n1, dn in zip(depositors, amounts, ns, dns):
            n2 = n1 + dn
            amm.deposit_range(depositor, amount, n1, n2)
            mint_for_testing(collateral_token, amm.address, amount)

    # Swap 0
    dy, dx = amm.get_dydx(0, 1, 0)
    assert dx == dy == 0
    with boa.reverts("Wrong index"):
        amm.get_dydx(1, 0, 0)

    # p_oracle is above the bands: nothing is sold
    dy, dx = amm.get_dydx(0, 1, 10**12 * 10**collateral_decimals)
    assert dx == dy == 0
    dx, dy = amm.get_dxdy(0, 1, 10**12 * 10**borrowed_decimals)
    assert dx == dy == 0

    # p_oracle at the bottom of the last band: all the bands are reached
    with boa.env.prank(admin):
        price_oracle.set_price(
            amm.p_oracle_down(max(n1 + dn for n1, dn in zip(ns, dns)))
        )
    boa.env.time_travel(600)  # To reset the prev p_o counter

    # Small swap
    dy1, dx1 = amm.get_dydx(0, 1, 10 ** (collateral_decimals - 2))
    dx2, dy2 = amm.get_dxdy(0, 1, dx1)
    assert dx1 == dx2
    if dy1 == 1 or dy2 == 1:
        assert abs(dy1 - dy2) <= 1
    else:
        assert abs(dy1 - dy2) <= collateral_precision

    # Small swap
    small_x_amount = amm.p_current_down(min(ns)) // 10 ** (
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

    with boa.reverts("Wrong index"):
        amm.get_dydx(1, 0, 10 ** (collateral_decimals - 2))

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

    with boa.reverts("Wrong index"):
        amm.get_dydx(1, 0, 10**12 * 10**collateral_decimals)


@given(
    amounts=st.lists(st.floats(min_value=0.01, max_value=1e6), min_size=5, max_size=5),
    ns=st.lists(st.integers(min_value=1, max_value=20), min_size=5, max_size=5),
    dns=st.lists(st.integers(min_value=0, max_value=20), min_size=5, max_size=5),
    amount=st.floats(min_value=0.001, max_value=10e9),
)
def test_exchange_dy_down_up(
    amm,
    price_oracle,
    amounts,
    ns,
    dns,
    amount,
    borrowed_token,
    collateral_token,
    admin,
):
    collateral_decimals = collateral_token.decimals()
    borrowed_decimals = borrowed_token.decimals()
    amounts = list(map(lambda x: int(x * 10**collateral_decimals), amounts))
    amount = int(amount * 10**borrowed_decimals)
    depositors = [boa.env.generate_address() for _ in range(5)]
    trader = boa.env.generate_address()
    with boa.env.prank(trader):
        borrowed_token.approve(amm.address, 2**256 - 1)
        collateral_token.approve(amm.address, 2**256 - 1)

    with boa.env.prank(admin):
        for depositor, amt, n1, dn in zip(depositors, amounts, ns, dns):
            n2 = n1 + dn
            if amt * 10 ** (18 - collateral_decimals) // (dn + 1) <= 100:
                with boa.reverts("Amount too low"):
                    amm.deposit_range(depositor, amt, n1, n2)
            else:
                amm.deposit_range(depositor, amt, n1, n2)
                mint_for_testing(collateral_token, amm.address, amt)

    # p_oracle is above the bands: nothing is sold
    dy, dx = amm.get_dydx(0, 1, amount)
    assert dx == 0 and dy == 0
    with boa.env.prank(trader):
        with boa.reverts("Slippage"):
            amm.exchange_dy(0, 1, amount, 2**256 - 1)

    # p_oracle at the bottom of the last band: all the bands are reached
    with boa.env.prank(admin):
        price_oracle.set_price(
            amm.p_oracle_down(max(n1 + dn for n1, dn in zip(ns, dns)))
        )
    boa.env.time_travel(600)  # To reset the prev p_o counter

    p_before = amm.get_p()

    # crvUSD --> ETH (dx - crvUSD, dy - ETH)
    dy, dx = amm.get_dydx(0, 1, amount)
    assert dy <= amount
    dy2, dx2 = amm.get_dydx(0, 1, dy)
    assert dy == dy2
    assert dx == pytest.approx(dx2, rel=1e-6)
    assert dy2 > 0
    mint_for_testing(borrowed_token, trader, dx2)
    with boa.env.prank(trader):
        with boa.reverts("Slippage"):
            amm.exchange_dy(0, 1, dy2, dx2 - 1)  # crvUSD --> ETH
        amm.exchange_dy(0, 1, dy2, dx2)  # crvUSD --> ETH
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

    # ETH --> crvUSD: collateral is never bought back
    with boa.reverts("Wrong index"):
        amm.get_dydx(1, 0, dx2)

    with boa.env.prank(trader):
        with boa.reverts("Wrong index"):
            amm.exchange_dy(1, 0, dx2, dy2)
    assert borrowed_token.balanceOf(trader) == 0
    assert collateral_token.balanceOf(trader) == dy2
    assert sum_borrowed == sum(amm.bands_x(i) for i in range(50))
    assert sum_collateral == sum(amm.bands_y(i) for i in range(50))
