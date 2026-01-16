import boa
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from tests.utils import mint_for_testing


@given(
    oracle_price=st.integers(min_value=2400 * 10**18, max_value=3750 * 10**18),
    n1=st.integers(min_value=1, max_value=50),
    dn=st.integers(min_value=0, max_value=49),
    deposit_amount=st.integers(min_value=10**12, max_value=10**20),
    init_trade_frac=st.floats(min_value=0.0, max_value=1.0),
    p_frac=st.floats(min_value=0.1, max_value=10),
)
@settings(max_examples=5000)
def test_amount_for_price(
    price_oracle,
    amm,
    accounts,
    collateral_token,
    borrowed_token,
    admin,
    get_price_oracle_band,
    oracle_price,
    n1,
    dn,
    deposit_amount,
    init_trade_frac,
    p_frac,
):
    deposit_amount = deposit_amount // 10 ** (18 - collateral_token.decimals())
    deposit_amount = max(deposit_amount, 101 * (dn + 1))
    user = accounts[0]
    with boa.env.prank(admin):
        amm.set_fee(0)
        price_oracle.set_price(oracle_price)
    boa.env.time_travel(3600)
    n2 = n1 + dn

    # Initial deposit
    with boa.env.prank(admin):
        amm.deposit_range(user, deposit_amount, n1, n2)
        mint_for_testing(collateral_token, amm.address, deposit_amount)

    with boa.env.prank(user):
        # Dump some to be somewhere inside the bands
        eamount = int(deposit_amount * amm.get_p() // 10**18 * init_trade_frac)
        if eamount > 0:
            mint_for_testing(borrowed_token, user, eamount)
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
            mint_for_testing(borrowed_token, user, amount)
            amm.exchange(0, 1, amount, 0)

        else:
            mint_for_testing(collateral_token, user, amount)
            amm.exchange(1, 0, amount, 0)

    p = amm.get_p()
    n_final = amm.active_band()

    if eamount > 0:
        assert abs(n_final - get_price_oracle_band()) < 50

    if p_final > p_max:
        p_final = p_max
    if p_final < p_min:
        p_final = p_min

    if p == pytest.approx(p_final, rel=1e-3):
        assert n1 <= n_final <= n2
    else:
        A = amm.A()
        a_ratio = A / (A - 1)
        if is_pump:
            if p_min == p_final:
                # The AMM gives the wrong price based on n0 band. It should be DUMP, not PUMP
                assert n_final == n0 and amount == 0
            else:
                # Nothing to pump for OR too far to pump
                _n_final = max(n_final, n1)
                p_o_ratio = amm.p_oracle_up(_n_final) / oracle_price
                assert collateral_token.balanceOf(
                    amm
                ) == 0 or p_o_ratio < a_ratio**-50 * (1 + 1e-8)
        else:
            if p_max == p_final:
                # The AMM gives the wrong price based on n0 band. It should be PUMP, not DUMP
                assert n_final == n0 and amount == 0
            else:
                # Nothing to dump for OR too far to dump
                _n_final = min(n_final, n2)
                p_o_ratio = amm.p_oracle_up(_n_final) / oracle_price
                assert borrowed_token.balanceOf(amm) == 0 or p_o_ratio > a_ratio**50 * (
                    1 - 1e-8
                )


def test_amount_for_price_ticks_too_far(
    price_oracle,
    amm,
    accounts,
    collateral_token,
    borrowed_token,
    admin,
    get_price_oracle_band,
):
    with boa.env.anchor():
        test_amount_for_price.hypothesis.inner_test(
            price_oracle,
            amm,
            accounts,
            collateral_token,
            borrowed_token,
            admin,
            get_price_oracle_band,
            oracle_price=2000000000000000000000,
            n1=50,
            dn=0,
            deposit_amount=1000000000000,
            init_trade_frac=0.0,
            p_frac=2891564947520759727 / 1e18,
        )
