from hypothesis import given, strategies, settings
import boa
from datetime import timedelta
from ..conftest import approx


@given(
    p_o_1=strategies.integers(min_value=2000 * 10**18, max_value=4000 * 10**18),
    p_o_2=strategies.integers(min_value=2000 * 10**18, max_value=4000 * 10**18),
    n1=strategies.integers(min_value=1, max_value=30),
    dn=strategies.integers(min_value=0, max_value=30),
    deposit_amount=strategies.integers(min_value=10**18, max_value=10**25),
)
@settings(max_examples=100, deadline=timedelta(seconds=1000))
def test_adiabatic(amm, price_oracle, collateral_token, borrowed_token, accounts, admin,
                   p_o_1, p_o_2, n1, dn, deposit_amount):
    N_STEPS = 101
    user = accounts[0]

    with boa.env.anchor():

        with boa.env.prank(admin):
            amm.set_fee(0)
            collateral_token._mint_for_testing(user, deposit_amount)
            amm.deposit_range(user, deposit_amount, dn, n1+dn, True)

        p_o = p_o_1
        p_o_mul = (p_o_2 / p_o_1) ** (1 / (N_STEPS - 1))
        precision = max(abs(p_o_mul - 1) * (dn + 1) * (max(p_o_2, p_o_1) / min(p_o_2, p_o_1)), 1e-6)  # Emprical formula

        x0 = 0
        y0 = 0

        for k in range(N_STEPS):
            with boa.env.prank(admin):
                price_oracle.set_price(p_o)

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
