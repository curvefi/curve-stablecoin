# Test that no losses are experienced when price oracle is adjusted

import boa
import pytest
from hypothesis import given, settings, example
from hypothesis import strategies as st


@pytest.fixture(scope="session")
def borrowed_token(get_borrowed_token):
    return get_borrowed_token(18)


@pytest.fixture(scope="session")
def amm(collateral_token, borrowed_token, get_amm):
    return get_amm(collateral_token, borrowed_token)


@given(
    n1=st.integers(min_value=1, max_value=60),  # Max is probably unreachable
    dn=st.integers(min_value=0, max_value=20),
    amount=st.integers(min_value=10**10, max_value=10**20),
    price_shift=st.floats(min_value=0.9, max_value=1.1)
)
@settings(max_examples=1000)
def test_buy_with_shift(amm, collateral_token, borrowed_token, price_oracle, accounts, admin,
                        n1, dn, amount, price_shift):
    user = accounts[1]
    collateral_amount = 10**18

    # Deposit
    with boa.env.prank(admin):
        amm.deposit_range(user, collateral_amount, n1, n1 + dn)
        collateral_token._mint_for_testing(amm.address, collateral_amount)

    # Swap stablecoin for collateral
    borrowed_token._mint_for_testing(user, amount)
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
    collateral_token._mint_for_testing(user, 10**24)  # BIG
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
    price_shift=st.floats(min_value=0.1, max_value=10)
)
@settings(max_examples=1000)
def test_sell_with_shift(amm, collateral_token, borrowed_token, price_oracle, accounts, admin,
                         n1, dn, amount, price_shift):
    user = accounts[1]
    collateral_amount = 10**18
    MANY = 10**24
    b_balances = []

    # Deposit
    with boa.env.prank(admin):
        amm.deposit_range(user, collateral_amount, n1, n1 + dn)
        collateral_token._mint_for_testing(amm.address, collateral_amount)

    # Swap max (buy)
    borrowed_token._mint_for_testing(user, MANY)
    with boa.env.prank(user):
        amm.exchange(0, 1, MANY, 0)

    # Swap back some amount (sell)
    b_balances += [borrowed_token.balanceOf(user)]
    amount = min(amount, collateral_token.balanceOf(user))
    with boa.env.prank(user):
        amm.exchange(1, 0, amount, 0)
    b_balances += [borrowed_token.balanceOf(user)]
    if b_balances[0] == b_balances[1]:
        return  # No swap -> stop it

    # Shift oracle
    with boa.env.prank(admin):
        price_oracle.set_price(int(price_oracle.price() * price_shift))

    # Swap max (buy) to trade back
    with boa.env.prank(user):
        amm.exchange(0, 1, MANY, 0)
    b_balances += [borrowed_token.balanceOf(user)]

    # Measure profit
    profit = b_balances[-1] - MANY
    assert profit <= 0


@given(
    n1=st.integers(min_value=20, max_value=60),  # Max is probably unreachable
    dn=st.integers(min_value=0, max_value=20),
    amount=st.integers(min_value=1, max_value=10**20),
    price_shift=st.floats(min_value=0.1, max_value=10)
)
@settings(max_examples=1000)
@example(n1=20, dn=0, amount=4351, price_shift=2.0)  # Leaves small dust
def test_no_untradable_funds(amm, collateral_token, borrowed_token, price_oracle, accounts, admin,
                             n1, dn, amount, price_shift):
    # Same as buy test at the beginning
    user = accounts[1]
    collateral_amount = 10**18

    # Deposit
    with boa.env.prank(admin):
        amm.deposit_range(user, collateral_amount, n1, n1 + dn)
        collateral_token._mint_for_testing(amm.address, collateral_amount)

    # Swap stablecoin for collateral
    borrowed_token._mint_for_testing(user, amount)
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
    collateral_token._mint_for_testing(user, 10**24)  # BIG
    with boa.env.prank(user):
        amm.exchange(1, 0, 10**24, 0)
    # Check that we cleaned up the last band
    new_b = borrowed_token.balanceOf(user)
    assert sum(amm.bands_x(n) for n in range(61)) == borrowed_token.balanceOf(amm.address), "Insolvent"
    assert amm.bands_x(n1) == 0
    assert new_b > b


@given(
    n1=st.integers(min_value=20, max_value=60),  # Max is probably unreachable
    dn=st.integers(min_value=0, max_value=20),
    amount=st.integers(min_value=1, max_value=10**20),
    price_shift=st.floats(min_value=0.1, max_value=10)
)
@settings(max_examples=1000)
@example(n1=20, dn=0, amount=4351, price_shift=2.0)  # Leaves small dust
def test_no_untradable_funds_in(amm, collateral_token, borrowed_token, price_oracle, accounts, admin,
                                n1, dn, amount, price_shift):
    # Same as test_no_untradable_funds but with exchange_dy
    user = accounts[1]
    collateral_amount = 10**18

    # Deposit
    with boa.env.prank(admin):
        amm.deposit_range(user, collateral_amount, n1, n1 + dn)
        collateral_token._mint_for_testing(amm.address, collateral_amount)

    # Swap stablecoin for collateral
    borrowed_token._mint_for_testing(user, amount)
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
    collateral_token._mint_for_testing(user, 10**24)  # BIG
    with boa.env.prank(user):
        amm.exchange_dy(1, 0, 10**24, 10**24)
    # Check that we cleaned up the last band
    new_b = borrowed_token.balanceOf(user)
    assert sum(amm.bands_x(n) for n in range(61)) == borrowed_token.balanceOf(amm.address), "Insolvent"
    assert amm.bands_x(n1) == 0
    assert new_b > b
