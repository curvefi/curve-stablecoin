from hypothesis import given, settings
from hypothesis import strategies as st
import boa
from ..conftest import approx
"""
Test that get_x_down and get_y_up don't change:
* if we do trades at constant p_o (immediate trades)
* or if we do adiabatic trade keeping p = p_o (adiabatic_trades)
"""


@given(
    p_o=st.integers(min_value=1000 * 10**18, max_value=10000 * 10**18),
    n1=st.integers(min_value=1, max_value=30),
    dn=st.integers(min_value=0, max_value=30),
    deposit_amount=st.integers(min_value=10**18, max_value=10**25),
    f_pump=st.floats(min_value=0, max_value=10),
    f_trade=st.floats(min_value=0, max_value=10),
    is_pump=st.booleans()
)
def test_immediate(amm, price_oracle, collateral_token, borrowed_token, accounts, admin,
                   p_o, n1, dn, deposit_amount, f_pump, f_trade, is_pump):
    user = accounts[0]
    with boa.env.prank(admin):
        price_oracle.set_price(p_o)
        amm.set_fee(0)
        amm.deposit_range(user, deposit_amount, n1, n1+dn)
        collateral_token._mint_for_testing(amm.address, deposit_amount)
    pump_amount = int(p_o * deposit_amount / 10**18 * f_pump / 10**12)
    with boa.env.prank(user):
        borrowed_token._mint_for_testing(user, pump_amount)
        boa.env.time_travel(600)  # To reset the prev p_o counter
        amm.exchange(0, 1, pump_amount, 0)
        while True:
            p_internal = amm.price_oracle()
            boa.env.time_travel(600)  # To reset the prev p_o counter
            amm.exchange(0, 1, 0, 0)
            if p_o == p_internal:
                break

    x0 = amm.get_x_down(user)
    y0 = amm.get_y_up(user)

    if is_pump:
        trade_amount = int(p_o * deposit_amount / 10**18 * f_trade / 10**12)
        with boa.env.prank(user):
            borrowed_token._mint_for_testing(user, trade_amount)
        i = 0
        j = 1
    else:
        trade_amount = int(deposit_amount * f_trade)
        with boa.env.prank(user):
            collateral_token._mint_for_testing(user, trade_amount)
        i = 1
        j = 0

    with boa.env.prank(user):
        amm.exchange(i, j, trade_amount, 0)

    x1 = amm.get_x_down(user)
    y1 = amm.get_y_up(user)

    assert approx(x0, x1, 1e-9, 100)
    assert approx(y0, y1, 1e-9, 100)


def test_immediate_above_p0(amm, price_oracle, collateral_token, borrowed_token, accounts, admin):
    deposit_amount = 5805319702344997833315303
    user = accounts[0]

    with boa.env.anchor():
        with boa.env.prank(admin):
            amm.set_fee(0)
            amm.deposit_range(user, deposit_amount, 6, 6)
            collateral_token._mint_for_testing(amm.address, deposit_amount)

        pump_amount = 3000 * deposit_amount * 147 // 10**18 // 10**12
        with boa.env.prank(user):
            borrowed_token._mint_for_testing(user, pump_amount)
            amm.exchange(0, 1, pump_amount, 0)

        x0 = amm.get_x_down(user)
        y0 = amm.get_y_up(user)

        trade_amount = deposit_amount * 52469 // 10**18
        collateral_token._mint_for_testing(user, trade_amount)

        with boa.env.prank(user):
            amm.exchange(1, 0, trade_amount, 0)

        x1 = amm.get_x_down(user)
        y1 = amm.get_y_up(user)

        assert x0 > 0
        assert x1 > 0
        assert approx(y0, deposit_amount, 1e-9)
        assert approx(x0, x1, 1e-9)
        assert approx(y0, y1, 1e-9)


def test_immediate_in_band(amm, price_oracle, collateral_token, borrowed_token, accounts, admin):
    deposit_amount = 835969548449222546344625

    with boa.env.anchor():
        user = accounts[0]
        with boa.env.prank(admin):
            amm.set_fee(0)
            amm.deposit_range(user, deposit_amount, 4, 4)
            collateral_token._mint_for_testing(amm.address, deposit_amount)

        pump_amount = 137
        with boa.env.prank(user):
            borrowed_token._mint_for_testing(user, pump_amount)
            amm.exchange(0, 1, pump_amount, 0)

        x0 = amm.get_x_down(user)
        y0 = amm.get_y_up(user)

        trade_amount = 2690425910633510  # 181406004646580
        with boa.env.prank(user):
            borrowed_token._mint_for_testing(user, trade_amount)
            amm.exchange(0, 1, trade_amount, 0)

        x1 = amm.get_x_down(user)
        y1 = amm.get_y_up(user)

        assert x0 > 0
        assert x1 > 0
        assert approx(y0, deposit_amount, 1e-9)
        assert approx(x0, x1, 1e-9)
        assert approx(y0, y1, 1e-9)


@given(
    p_o_1=st.integers(min_value=2000 * 10**18, max_value=4000 * 10**18),
    p_o_2=st.integers(min_value=2000 * 10**18, max_value=4000 * 10**18),
    n1=st.integers(min_value=1, max_value=30),
    dn=st.integers(min_value=0, max_value=30),
    deposit_amount=st.integers(min_value=10**18, max_value=10**25),
)
@settings(max_examples=100)
def test_adiabatic(amm, price_oracle, collateral_token, borrowed_token, accounts, admin,
                   p_o_1, p_o_2, n1, dn, deposit_amount):
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
            borrowed_token._mint_for_testing(user, amount)
        else:
            i = 1
            j = 0
            collateral_token._mint_for_testing(user, amount)

        with boa.env.prank(user):
            amm.exchange(i, j, amount, 0)

        if k == 0:
            x0 = amm.get_x_down(user)
            y0 = amm.get_y_up(user)

        x = amm.get_x_down(user)
        y = amm.get_y_up(user)
        assert approx(x, x0, precision)
        assert approx(y, y0, precision)

        if k != N_STEPS - 1:
            p_o = int(p_o * p_o_mul)


def test_adiabatic_fail_1(amm, price_oracle, collateral_token, borrowed_token, accounts, admin):
    with boa.env.anchor():
        test_adiabatic.hypothesis.inner_test(
            amm, price_oracle, collateral_token, borrowed_token, accounts, admin,
            p_o_1=2296376199582847058288, p_o_2=2880636282130384399567, n1=19, dn=0, deposit_amount=1000000000000000000)
