import boa
from ..conftest import approx
from hypothesis import given, settings
from hypothesis import strategies as st


@given(
    oracle_price=st.integers(min_value=2400 * 10**18, max_value=3750 * 10**18),
    n1=st.integers(min_value=1, max_value=50),
    dn=st.integers(min_value=0, max_value=49),
    deposit_amount=st.integers(min_value=10**12, max_value=10**20),
    init_trade_frac=st.floats(min_value=0.0, max_value=1.0),
    p_frac=st.floats(min_value=0.1, max_value=10)
)
@settings(max_examples=500)
def test_amount_for_price(price_oracle, amm, accounts, collateral_token, borrowed_token, admin,
                          oracle_price, n1, dn, deposit_amount, init_trade_frac, p_frac):
    user = accounts[0]
    with boa.env.prank(admin):
        amm.set_fee(0)
        price_oracle.set_price(oracle_price)
    n2 = n1 + dn

    # Initial deposit
    with boa.env.prank(admin):
        amm.deposit_range(user, deposit_amount, n1, n2)
        collateral_token._mint_for_testing(amm.address, deposit_amount)

    with boa.env.prank(user):
        # Dump some to be somewhere inside the bands
        eamount = int(deposit_amount * amm.get_p() // 10**18 * init_trade_frac)
        if eamount > 0:
            borrowed_token._mint_for_testing(user, eamount)
        boa.env.time_travel(600)  # To reset the prev p_o counter
        amm.exchange(0, 1, eamount, 0)
        n0 = amm.active_band()

        p_initial = amm.get_p()
        p_final = int(p_initial * p_frac)
        p_max = amm.p_current_up(n2)
        p_min = amm.p_current_down(n1)

        amount, is_pump = amm.get_amount_for_price(p_final)

        assert is_pump == (p_final >= p_initial)

        if is_pump:
            borrowed_token._mint_for_testing(user, amount)
            amm.exchange(0, 1, amount, 0)

        else:
            collateral_token._mint_for_testing(user, amount)
            amm.exchange(1, 0, amount, 0)

    p = amm.get_p()

    prec = 1e-6
    if amount > 0:
        if is_pump:
            prec = max(2 / amount + 2 / (1e12 * amount * 1e18 / p_max), prec)
        else:
            prec = max(2 / amount + 2 / (amount * p_max / 1e18 / 1e12), prec)
    else:
        return

    n_final = amm.active_band()

    assert approx(p_max, amm.p_current_up(n2), 1e-8)
    assert approx(p_min, amm.p_current_down(n1), 1e-8)

    if abs(n_final - n0) < 50 - 1 and prec < 0.1:
        A = amm.A()
        a_ratio = A / (A - 1)
        p_o_ratio = amm.p_oracle_up(n_final) / amm.price_oracle()
        if is_pump:
            if p_o_ratio < a_ratio**-50 * (1 + 1e-8):
                return
        else:
            if p_o_ratio > a_ratio**50 * (1 - 1e-8):
                return

        if p_final > p_min * (1 + prec) and p_final < p_max * (1 - prec):
            assert approx(p, p_final, prec)

        elif p_final >= p_max * (1 - prec):
            if not approx(p, p_max, prec):
                assert n_final > n2

        elif p_final <= p_min * (1 + prec):
            if not approx(p, p_min, prec):
                assert n_final < n1


def test_amount_for_price_ticks_too_far(price_oracle, amm, accounts, collateral_token, borrowed_token, admin):
    with boa.env.anchor():
        test_amount_for_price.hypothesis.inner_test(
            price_oracle, amm, accounts, collateral_token, borrowed_token, admin,
            oracle_price=2000000000000000000000,
            n1=50,
            dn=0,
            deposit_amount=1000000000000,
            init_trade_frac=0.0,
            p_frac=2891564947520759727/1e18)
