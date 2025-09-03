import boa
import pytest
from hypothesis import given
from hypothesis import strategies as st

min_default_borrow_rate = 5 * 10**15 // (365 * 86400)
max_default_borrow_rate = 50 * 10**16 // (365 * 86400)


@given(fill=st.floats(min_value=0.0, max_value=2.0))
def test_monetary_policy(controller, collateral_token, borrowed_token, monetary_policy, admin, fill):
    available = borrowed_token.balanceOf(controller.address)
    to_borrow = int(fill * available)
    c_amount = 2 * 3000 * to_borrow * 10**(18 - borrowed_token.decimals()) // 10**(18 - collateral_token.decimals())

    if to_borrow > 0 and c_amount > 0:
        with boa.env.prank(admin):
            collateral_token.approve(controller.address, 2**256 - 1)
            boa.deal(collateral_token, admin, c_amount)
            if to_borrow > available:
                with boa.reverts():
                    controller.create_loan(c_amount, to_borrow, 5)
                return
            else:
                controller.create_loan(c_amount, to_borrow, 5)
                rate = monetary_policy.rate(controller.address)
                assert rate >= min_default_borrow_rate * (1 - 1e-5)
                assert rate <= max_default_borrow_rate * (1 + 1e-5)
                theoretical_rate = min_default_borrow_rate * (max_default_borrow_rate / min_default_borrow_rate)**fill
                assert rate == pytest.approx(theoretical_rate, rel=1e-4)
