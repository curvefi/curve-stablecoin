import boa
from hypothesis import given
from hypothesis import strategies as st
from ..conftest import approx

min_default_borrow_rate = 5 * 10**15 // (365 * 86400)
max_default_borrow_rate = 50 * 10**16 // (365 * 86400)


@given(fill=st.floats(min_value=0.0, max_value=2.0))
def test_monetary_policy(filled_controller, collateral_token, borrowed_token, market_mpolicy, admin, fill):
    available = borrowed_token.balanceOf(filled_controller)
    to_borrow = int(fill * available)
    c_amount = 2 * 3000 * to_borrow * 10**(18 - borrowed_token.decimals()) // 10**(18 - collateral_token.decimals())

    if to_borrow > 0 and c_amount > 0:
        with boa.env.prank(admin):
            collateral_token.approve(filled_controller, 2**256 - 1)
            collateral_token._mint_for_testing(admin, c_amount)
            if to_borrow > available:
                with boa.reverts():
                    filled_controller.create_loan(c_amount, to_borrow, 5)
                return
            else:
                filled_controller.create_loan(c_amount, to_borrow, 5)
                rate = market_mpolicy.rate(filled_controller)
                assert rate >= min_default_borrow_rate * (1 - 1e-5)
                assert rate <= max_default_borrow_rate * (1 + 1e-5)
                theoretical_rate = min_default_borrow_rate * (max_default_borrow_rate / min_default_borrow_rate)**fill
                assert approx(rate, theoretical_rate, 1e-4)
