from ..conftest import approx
from brownie.test import given, strategy


@given(
    oracle_price=strategy('uint256', min_value=2000 * 10**18, max_value=4000 * 10**18),
    n1=strategy('int256', min_value=1, max_value=50),
    dn=strategy('uint256', min_value=0, max_value=49),
    deposit_amount=strategy('uint256', min_value=10**12, max_value=10**20),
    init_trade_frac=strategy('uint256', max_value=10**18),
    p_frac=strategy('uint256', min_value=10**17, max_value=10**19)
)
def test_amount_for_price(PriceOracle, amm, accounts, collateral_token, borrowed_token,
                          oracle_price, n1, dn, deposit_amount, init_trade_frac, p_frac):
    admin = accounts[0]
    user = accounts[1]
    PriceOracle.set_price(oracle_price, {'from': admin})
    n2 = n1 + dn

    # Initial deposit
    collateral_token._mint_for_testing(user, deposit_amount)
    amm.deposit_range(user, deposit_amount, n1, n2, True, {'from': admin})

    # Dump some to be somewhere inside the bands
    eamount = deposit_amount * amm.get_p() // 10**18 * init_trade_frac // 10**18
    if eamount > 0:
        borrowed_token._mint_for_testing(user, eamount)
        amm.exchange(0, 1, eamount, 0, {'from': user})
    n0 = amm.active_band()

    p_initial = amm.get_p()
    p_final = p_initial * p_frac // 10**18
    p_max = amm.p_current_up(n2)
    p_min = amm.p_current_down(n1)

    amount, is_pump = amm.get_amount_for_price(p_final)

    assert is_pump == (p_final >= p_initial)

    if is_pump:
        borrowed_token._mint_for_testing(user, amount)
        amm.exchange(0, 1, amount, 0, {'from': user})

    else:
        collateral_token._mint_for_testing(user, amount)
        amm.exchange(1, 0, amount, 0, {'from': user})

    p = amm.get_p()

    prec = max(1e-6, (amm.fee() / 1e18)**2)
    if amount > 0:
        if is_pump:
            prec = max(2 / amount + 2 / (1e12 * amount * 1e18 / p_max), prec)
        else:
            prec = max(2 / amount + 2 / (amount * p_max / 1e18 / 1e12), prec)
    else:
        return

    if p > p_min * (1 + prec) and p < p_max * (1 - prec) and abs(amm.active_band() - n0) < 50 - 1:
        if prec < 0.1:
            assert approx(p, p_final, prec)
