from hypothesis import given, settings
from hypothesis import strategies as st
import boa
import pytest
from ..conftest import approx
"""
Test that get_x_down and get_y_up don't change:
* if we do trades at constant p_o (immediate trades)
* or if we do adiabatic trade keeping p = p_o (adiabatic_trades)
"""


@pytest.fixture(scope="module")
def borrowed_token(get_borrowed_token):
    return get_borrowed_token(18)


@pytest.fixture(scope="module")
def amm(get_amm, borrowed_token, collateral_token):
    return get_amm(collateral_token, borrowed_token)


@given(
    p_o=st.integers(min_value=1000 * 10**18, max_value=10000 * 10**18),
    n1=st.integers(min_value=1, max_value=30),
    dn=st.integers(min_value=0, max_value=30),
    deposit_amount=st.floats(min_value=1e-9, max_value=1e7),
    f_pump=st.floats(min_value=0, max_value=10),
    f_trade=st.floats(min_value=0, max_value=10),
    is_pump=st.booleans()
)
def test_immediate(amm, price_oracle, collateral_token, borrowed_token, accounts, admin,
                   p_o, n1, dn, deposit_amount, f_pump, f_trade, is_pump):
    collateral_decimals = collateral_token.decimals()
    borrowed_decimals = borrowed_token.decimals()
    deposit_amount = int(deposit_amount * 10**collateral_decimals)
    user = accounts[0]
    with boa.env.prank(admin):
        price_oracle.set_price(p_o)
        amm.set_fee(0)
        amm.deposit_range(user, deposit_amount, n1, n1+dn)
        collateral_token._mint_for_testing(amm.address, deposit_amount)
        while True:
            p_internal = amm.price_oracle()
            boa.env.time_travel(600)  # To reset the prev p_o counter
            amm.exchange(0, 1, 0, 0)
            if p_o == p_internal:
                break

    pump_recv_amount = int(deposit_amount * f_pump)
    pump_recv_amount, pump_amount = amm.get_dydx(0, 1, pump_recv_amount)
    with boa.env.prank(user):
        borrowed_token._mint_for_testing(user, pump_amount)
        amm.exchange_dy(0, 1, pump_recv_amount, pump_amount)

    x0 = amm.get_x_down(user)
    y0 = amm.get_y_up(user)
    if is_pump:
        trade_recv_amount = int(deposit_amount * f_trade)
        trade_recv_amount, trade_amount = amm.get_dydx(0, 1, trade_recv_amount)
        with boa.env.prank(user):
            borrowed_token._mint_for_testing(user, trade_amount)
        i = 0
        j = 1
    else:
        trade_recv_amount = int(p_o * deposit_amount / 10**collateral_decimals * f_trade / 10**(collateral_decimals - borrowed_decimals))
        trade_recv_amount, trade_amount = amm.get_dydx(1, 0, trade_recv_amount)
        with boa.env.prank(user):
            collateral_token._mint_for_testing(user, trade_amount)
        i = 1
        j = 0

    with boa.env.prank(user):
        amm.exchange_dy(i, j, trade_recv_amount, trade_amount)

    x1 = amm.get_x_down(user)
    y1 = amm.get_y_up(user)

    assert approx(x0, x1, 1e-6, 100)
    assert approx(y0, y1, 1e-6, 100)


@given(
    p_o_1=st.integers(min_value=2000 * 10**18, max_value=4000 * 10**18),
    p_o_2=st.integers(min_value=2000 * 10**18, max_value=4000 * 10**18),
    n1=st.integers(min_value=1, max_value=30),
    dn=st.integers(min_value=0, max_value=30),
    deposit_amount=st.floats(min_value=1, max_value=1e7),
)
@settings(max_examples=100)
def test_adiabatic(amm, price_oracle, collateral_token, borrowed_token, accounts, admin,
                   p_o_1, p_o_2, n1, dn, deposit_amount):
    collateral_decimals = collateral_token.decimals()
    deposit_amount = int(deposit_amount * 10 ** collateral_decimals)
    N_STEPS = 101
    user = accounts[0]

    with boa.env.prank(admin):
        amm.set_fee(0)
        amm.deposit_range(user, deposit_amount, dn, n1+dn)
        collateral_token._mint_for_testing(amm.address, deposit_amount)
        for i in range(2):
            boa.env.time_travel(600)
            price_oracle.set_price(p_o_1)
            amm.exchange(0, 1, 0, 0)

    p_o = p_o_1
    p_o_mul = (p_o_2 / p_o_1) ** (1 / (N_STEPS - 1))
    precision = max(1.5 * abs(p_o_mul - 1) * (dn + 1) * (max(p_o_2, p_o_1) / min(p_o_2, p_o_1)), 1e-6)  # Emprical formula
    precision += 1 - min(p_o_mul, 1 / p_o_mul)**3  # Dynamic fee component

    x0 = 0
    y0 = 0

    for k in range(N_STEPS):
        boa.env.time_travel(600)
        with boa.env.prank(admin):
            price_oracle.set_price(p_o)
        boa.env.time_travel(600)

        amount, is_pump = amm.get_amount_for_price(p_o)

        if is_pump:
            i = 0
            j = 1
            recv_amount = amm.get_dy(i, j, amount)
            _amount = amm.get_dx(i, j, recv_amount)
            borrowed_token._mint_for_testing(user, _amount)
        else:
            i = 1
            j = 0
            recv_amount = amm.get_dy(i, j, amount)
            _amount = amm.get_dx(i, j, recv_amount)
            collateral_token._mint_for_testing(user, _amount)

        with boa.env.prank(user):
            amm.exchange_dy(i, j, recv_amount, _amount)

        if k == 0:
            x0 = amm.get_x_down(user)
            y0 = amm.get_y_up(user)

        x = amm.get_x_down(user)
        y = amm.get_y_up(user)
        assert approx(x, x0, precision)
        assert approx(y, y0, precision)

        if k != N_STEPS - 1:
            p_o = int(p_o * p_o_mul)
