# Test that no losses are experienced when price oracle is adjusted

import boa
import pytest
from hypothesis import given, settings, example
from hypothesis import strategies as st
from tests.utils import mint_for_testing


@pytest.fixture(scope="module")
def amm(collateral_token, borrowed_token, get_amm):
    return get_amm(collateral_token, borrowed_token)


@given(
    n1=st.integers(min_value=1, max_value=60),  # Max is probably unreachable
    dn=st.integers(min_value=0, max_value=20),
    amount=st.integers(min_value=10**10, max_value=10**20),
    price_shift=st.floats(min_value=0.9, max_value=1.1),
)
@settings(max_examples=1000)
def test_buy_with_shift(
    amm,
    collateral_token,
    borrowed_token,
    price_oracle,
    admin,
    n1,
    dn,
    amount,
    price_shift,
):
    user = boa.env.generate_address()
    with boa.env.prank(user):
        collateral_token.approve(amm.address, 2**256 - 1)
        borrowed_token.approve(amm.address, 2**256 - 1)
    collateral_amount = 10 ** collateral_token.decimals()

    # Deposit
    with boa.env.prank(admin):
        amm.deposit_range(user, collateral_amount, n1, n1 + dn)
        mint_for_testing(collateral_token, amm.address, collateral_amount)

    # Swap stablecoin for collateral
    mint_for_testing(borrowed_token, user, amount)
    with boa.env.prank(user):
        amm.exchange(0, 1, amount, 0)
    b = borrowed_token.balanceOf(user)
    if b < amount:
        collateral_amount = collateral_token.balanceOf(user)
        assert collateral_amount != 0
    else:
        return  # No real swap

    # Shift oracle
    with boa.env.prank(admin):
        price_oracle.set_price(int(price_oracle.price() * price_shift))

    # Trade back
    mint_for_testing(collateral_token, user, 10**24)  # BIG
    with boa.env.prank(user):
        amm.exchange(1, 0, 10**24, 0)
    # Check that we cleaned up the last band
    new_b = borrowed_token.balanceOf(user)
    assert new_b > b
    collateral_amount = collateral_token.balanceOf(user) - 10**24

    # Measure profit
    assert collateral_amount <= 0


@given(
    n1=st.integers(min_value=1, max_value=20),  # Max is probably unreachable
    dn=st.integers(min_value=0, max_value=20),
    amount=st.integers(min_value=10**10, max_value=10**18),
    price_shift=st.floats(min_value=0.1, max_value=10),
)
@settings(max_examples=1000)
def test_sell_with_shift(
    amm,
    collateral_token,
    borrowed_token,
    price_oracle,
    admin,
    n1,
    dn,
    amount,
    price_shift,
):
    user = boa.env.generate_address()
    with boa.env.prank(user):
        collateral_token.approve(amm.address, 2**256 - 1)
        borrowed_token.approve(amm.address, 2**256 - 1)
    collateral_amount = 10 ** collateral_token.decimals()
    MANY = 10**24
    b_balances = [MANY]
    c_balances = [0]

    # Deposit
    with boa.env.prank(admin):
        amm.deposit_range(user, collateral_amount, n1, n1 + dn)
        mint_for_testing(collateral_token, amm.address, collateral_amount)
        # Collateral is sold only from bands which p_oracle has reached
        price_oracle.set_price((amm.p_oracle_up(n1) + amm.p_oracle_down(n1)) // 2)
    boa.env.time_travel(600)  # To reset the prev p_o counter

    # Swap max (buy)
    mint_for_testing(borrowed_token, user, MANY)
    with boa.env.prank(user):
        amm.exchange(0, 1, MANY, 0)
    assert amm.active_band() == n1
    b_balances += [borrowed_token.balanceOf(user)]
    c_balances += [collateral_token.balanceOf(user)]

    # Swap back some amount (sell): nothing is bought back
    amount = min(amount, collateral_token.balanceOf(user))
    with boa.env.prank(user):
        with boa.reverts("Wrong index"):
            amm.exchange(1, 0, amount, 0)
    assert borrowed_token.balanceOf(user) == b_balances[1] < MANY

    # Shift oracle
    with boa.env.prank(admin):
        price_oracle.set_price(int(price_oracle.price() * price_shift))

    # Swap max (buy) again
    with boa.env.prank(user):
        amm.exchange(0, 1, MANY, 0)
    b_balances += [borrowed_token.balanceOf(user)]
    c_balances += [collateral_token.balanceOf(user)]

    # Measure profit
    profit = b_balances[-1] - MANY
    assert profit <= 0
    # The shift does not make the collateral cheaper
    dx = [b_balances[0] - b_balances[1], b_balances[1] - b_balances[2]]
    dy = [c_balances[1] - c_balances[0], c_balances[2] - c_balances[1]]
    # The collateral bought is rounded down
    assert dx[1] * (dy[0] + 1) >= dx[0] * dy[1]


@given(
    n1=st.integers(min_value=20, max_value=60),  # Max is probably unreachable
    dn=st.integers(min_value=0, max_value=20),
    amount=st.integers(min_value=1, max_value=10**20),
    price_shift=st.floats(min_value=0.1, max_value=10),
)
@settings(max_examples=1000)
@example(n1=20, dn=0, amount=4351, price_shift=2.0)  # Leaves small dust
def test_no_untradable_funds(
    amm,
    collateral_token,
    borrowed_token,
    price_oracle,
    admin,
    n1,
    dn,
    amount,
    price_shift,
):
    # Same as buy test at the beginning
    user = boa.env.generate_address()
    with boa.env.prank(user):
        collateral_token.approve(amm.address, 2**256 - 1)
        borrowed_token.approve(amm.address, 2**256 - 1)
    collateral_amount = 10 ** collateral_token.decimals()

    # Deposit
    with boa.env.prank(admin):
        amm.deposit_range(user, collateral_amount, n1, n1 + dn)
        mint_for_testing(collateral_token, amm.address, collateral_amount)

    # Swap stablecoin for collateral
    mint_for_testing(borrowed_token, user, amount)
    with boa.env.prank(user):
        amm.exchange(0, 1, amount, 0)
    b = borrowed_token.balanceOf(user)
    if b < amount:
        collateral_amount = collateral_token.balanceOf(user)
        assert collateral_amount != 0
    else:
        return  # No real swap

    # Shift oracle
    with boa.env.prank(admin):
        price_oracle.set_price(int(price_oracle.price() * price_shift))

    # Trade back
    mint_for_testing(collateral_token, user, 10**24)  # BIG
    with boa.env.prank(user):
        amm.exchange(1, 0, 10**24, 0)
    # Check that we cleaned up the last band
    new_b = borrowed_token.balanceOf(user)
    if borrowed_token.decimals() == 18:
        assert sum(amm.bands_x(n) for n in range(61)) == borrowed_token.balanceOf(
            amm.address
        ), "Insolvent"
    else:
        assert (
            0
            <= borrowed_token.balanceOf(amm.address)
            - sum(amm.bands_x(n) for n in range(61))
            <= 1
        ), "Insolvent"
    assert amm.bands_x(n1) == 0
    assert new_b > b


@given(
    n1=st.integers(min_value=20, max_value=60),  # Max is probably unreachable
    dn=st.integers(min_value=0, max_value=20),
    amount=st.integers(min_value=1, max_value=10**20),
    price_shift=st.floats(min_value=0.1, max_value=10),
)
@settings(max_examples=1000)
@example(n1=20, dn=0, amount=4351, price_shift=2.0)  # Leaves small dust
def test_no_untradable_funds_in(
    amm,
    collateral_token,
    borrowed_token,
    price_oracle,
    admin,
    n1,
    dn,
    amount,
    price_shift,
):
    # Same as test_no_untradable_funds but with exchange_dy
    user = boa.env.generate_address()
    with boa.env.prank(user):
        collateral_token.approve(amm.address, 2**256 - 1)
        borrowed_token.approve(amm.address, 2**256 - 1)
    collateral_amount = 10 ** collateral_token.decimals()

    # Deposit
    with boa.env.prank(admin):
        amm.deposit_range(user, collateral_amount, n1, n1 + dn)
        mint_for_testing(collateral_token, amm.address, collateral_amount)

    # Swap stablecoin for collateral
    mint_for_testing(borrowed_token, user, amount)
    with boa.env.prank(user):
        amm.exchange(0, 1, amount, 0)
    b = borrowed_token.balanceOf(user)
    if b < amount:
        collateral_amount = collateral_token.balanceOf(user)
        assert collateral_amount != 0
    else:
        return  # No real swap

    # Shift oracle
    with boa.env.prank(admin):
        price_oracle.set_price(int(price_oracle.price() * price_shift))

    # Trade back
    mint_for_testing(collateral_token, user, 10**24)  # BIG
    with boa.env.prank(user):
        price_oracle.price_w()
        amm.exchange_dy(1, 0, 2**256 - 1, 10**24)
    # Check that we cleaned up the last band
    new_b = borrowed_token.balanceOf(user)
    if borrowed_token.decimals() == 18:
        assert sum(amm.bands_x(n) for n in range(61)) == borrowed_token.balanceOf(
            amm.address
        ), "Insolvent"
    else:
        assert (
            0
            <= borrowed_token.balanceOf(amm.address)
            - sum(amm.bands_x(n) for n in range(61))
            <= 1
        ), "Insolvent"
    assert amm.bands_x(n1) == 0
    assert new_b > b
