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
    deposit_amount = max(deposit_amount, dn + 1)

    user = boa.env.generate_address()
    with boa.env.prank(user):
        collateral_token.approve(amm.address, 2**256 - 1)
        borrowed_token.approve(amm.address, 2**256 - 1)

    with boa.env.prank(admin):
        amm.eval(f"self.fee = 0")
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
            if amm.get_dy(0, 1, amount) == 0:
                # Nothing is quoted only if no collateral is left, p_oracle has not reached
                # the next band which holds it or the target is short of that band
                bands = (n for n in range(max(n0, n1), n2 + 1) if amm.bands_y(n) > 0)
                n = next(bands, None)
                assert (
                    amount > 0
                    or n is None
                    or amm.p_oracle_up(n) < amm.price_oracle()
                    or p_final <= max(p_initial, amm.p_current_down(n)) * (1 + 1e-3)
                )
                return
            amm.exchange(0, 1, amount, 0)
            # Collateral is sold only from bands which p_oracle has reached
            assert amm.p_oracle_up(amm.active_band()) >= amm.price_oracle()
        else:
            # Only a pump can move the price: nothing is bought back
            assert amount == 0

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
                # Nothing to pump for OR too far to pump OR p_oracle is still in this band
                # and the band is bought out (the AMM's rounding keeps at most 1 wei)
                _n_final = max(n_final, n1)
                p_o_ratio = amm.p_oracle_up(_n_final) / oracle_price
                p_o = amm.price_oracle()
                assert (
                    collateral_token.balanceOf(amm) == 0
                    or p_o_ratio < a_ratio**-50 * (1 + 1e-8)
                    or (
                        amm.p_oracle_down(n_final) < p_o <= amm.p_oracle_up(n_final)
                        and amm.bands_y(n_final) <= 1
                    )
                )
        else:
            # The price stays where it was
            assert n_final == n0 and p == p_initial


def test_amount_for_price_ticks_too_far(
    price_oracle,
    amm,
    collateral_token,
    borrowed_token,
    admin,
    get_price_oracle_band,
):
    with boa.env.anchor():
        test_amount_for_price.hypothesis.inner_test(
            price_oracle,
            amm,
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
