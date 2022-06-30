from ..conftest import approx
from hypothesis import settings
from brownie.test import given, strategy
"""
Test that get_x_down and get_y_up don't change:
* if we do trades at constant p_o (immediate trades)
* or if we do adiabatic trade keeping p = p_o (adiabatic_trades)
"""


@given(
    p_o=strategy('uint256', min_value=1000 * 10**18, max_value=10000 * 10**18),
    n1=strategy('uint256', min_value=1, max_value=30),
    dn=strategy('uint256', max_value=30),
    deposit_amount=strategy('uint256', min_value=10**9, max_value=10**25),
    f_pump=strategy('uint256', max_value=10**19),
    f_trade=strategy('uint256', max_value=10**19),
    is_pump=strategy('bool')
)
def test_immediate(amm, PriceOracle, collateral_token, borrowed_token, accounts,
                   p_o, n1, dn, deposit_amount, f_pump, f_trade, is_pump):
    admin = accounts[0]
    user = accounts[1]
    PriceOracle.set_price(p_o)
    amm.set_fee(0, {'from': admin})
    collateral_token._mint_for_testing(user, deposit_amount, {'from': user})
    amm.deposit_range(user, deposit_amount, n1, n1+dn, True, {'from': admin})
    pump_amount = p_o * deposit_amount // 10**18 * f_pump // 10**18 // 10**12
    borrowed_token._mint_for_testing(user, pump_amount, {'from': user})
    amm.exchange(0, 1, pump_amount, 0, {'from': user})

    x0 = amm.get_x_down(user)
    y0 = amm.get_y_up(user)

    if is_pump:
        trade_amount = p_o * deposit_amount // 10**18 * f_trade // 10**18 // 10**12
        borrowed_token._mint_for_testing(user, trade_amount, {'from': user})
        i = 0
        j = 1
    else:
        trade_amount = deposit_amount * f_trade // 10**18
        collateral_token._mint_for_testing(user, trade_amount, {'from': user})
        i = 1
        j = 0

    amm.exchange(i, j, trade_amount, 0, {'from': user})

    x1 = amm.get_x_down(user)
    y1 = amm.get_y_up(user)

    assert approx(x0, x1, 1e-9, 100)
    assert approx(y0, y1, 1e-9, 100)


def test_immediate_above_p0(amm, PriceOracle, collateral_token, borrowed_token, accounts):
    deposit_amount = 5805319702344997833315303

    admin = accounts[0]
    user = accounts[1]
    amm.set_fee(0, {'from': admin})
    collateral_token._mint_for_testing(user, deposit_amount, {'from': user})
    amm.deposit_range(user, deposit_amount, 6, 6, True, {'from': admin})
    pump_amount = 3000 * deposit_amount * 147 // 10**18 // 10**12
    borrowed_token._mint_for_testing(user, pump_amount, {'from': user})
    amm.exchange(0, 1, pump_amount, 0, {'from': user})

    x0 = amm.get_x_down(user)
    y0 = amm.get_y_up(user)

    trade_amount = deposit_amount * 52469 // 10**18
    collateral_token._mint_for_testing(user, trade_amount, {'from': user})

    amm.exchange(1, 0, trade_amount, 0, {'from': user})

    x1 = amm.get_x_down(user)
    y1 = amm.get_y_up(user)

    assert x0 > 0
    assert x1 > 0
    assert approx(y0, deposit_amount, 1e-9)
    assert approx(x0, x1, 1e-9)
    assert approx(y0, y1, 1e-9)


def test_immediate_in_band(amm, PriceOracle, collateral_token, borrowed_token, accounts):
    deposit_amount = 835969548449222546344625

    admin = accounts[0]
    user = accounts[1]
    amm.set_fee(0, {'from': admin})
    collateral_token._mint_for_testing(user, deposit_amount, {'from': user})
    amm.deposit_range(user, deposit_amount, 4, 4, True, {'from': admin})
    pump_amount = 137
    borrowed_token._mint_for_testing(user, pump_amount, {'from': user})
    amm.exchange(0, 1, pump_amount, 0, {'from': user})

    x0 = amm.get_x_down(user)
    y0 = amm.get_y_up(user)

    trade_amount = 2690425910633510  # 181406004646580
    borrowed_token._mint_for_testing(user, trade_amount, {'from': user})

    amm.exchange(0, 1, trade_amount, 0, {'from': user})

    x1 = amm.get_x_down(user)
    y1 = amm.get_y_up(user)

    assert x0 > 0
    assert x1 > 0
    assert approx(y0, deposit_amount, 1e-9)
    assert approx(x0, x1, 1e-9)
    assert approx(y0, y1, 1e-9)


@given(
    p_o_1=strategy('uint256', min_value=2000 * 10**18, max_value=4000 * 10**18),
    p_o_2=strategy('uint256', min_value=2000 * 10**18, max_value=4000 * 10**18),
    n1=strategy('uint256', min_value=1, max_value=30),
    dn=strategy('uint256', max_value=0),  # XXX 30
    deposit_amount=strategy('uint256', min_value=10**9, max_value=10**25),
)
@settings(max_examples=10)
def test_adiabatic(amm, PriceOracle, collateral_token, borrowed_token, accounts,
                   p_o_1, p_o_2, n1, dn, deposit_amount):
    admin = accounts[0]
    user = accounts[1]
    amm.set_fee(0, {'from': admin})
    collateral_token._mint_for_testing(user, deposit_amount, {'from': user})
    amm.deposit_range(user, deposit_amount, n1, n1+dn, True, {'from': admin})

    N_STEPS = 101
    p_o = p_o_1
    p_o_mul = (p_o_2 / p_o_1) ** (1 / (N_STEPS - 1))
    precision = max(abs(p_o_mul - 1), 1e-6)

    x0 = 0
    y0 = 0

    for k in range(N_STEPS):
        PriceOracle.set_price(p_o)

        if k == 0:
            x0 = amm.get_x_down(user)
            y0 = amm.get_y_up(user)

        amount, is_pump = amm.get_amount_for_price(p_o)
        if is_pump:
            i = 0
            j = 1
            borrowed_token._mint_for_testing(user, amount, {'from': user})
        else:
            i = 1
            j = 0
            collateral_token._mint_for_testing(user, amount, {'from': user})

        amm.exchange(i, j, amount, 0, {'from': user})

        x = amm.get_x_down(user)
        y = amm.get_y_up(user)
        assert approx(x, x0, precision)
        assert approx(y, y0, precision)

        if k != N_STEPS - 1:
            p_o = int(p_o_1 * p_o_mul)
