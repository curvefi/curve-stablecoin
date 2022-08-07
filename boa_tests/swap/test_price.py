import boa
from hypothesis import given, settings
from hypothesis import strategies as st
from datetime import timedelta
from ..conftest import approx


@given(
    amount=st.integers(min_value=1, max_value=10**6),
    ix=st.integers(min_value=0, max_value=1))
@settings(max_examples=100, deadline=timedelta(seconds=1000))
def test_price(swap_w_d, redeemable_coin, volatile_coin, accounts, amount, ix):
    user = accounts[0]
    assert swap_w_d.get_p() == 10**18
    from_coin = [redeemable_coin, volatile_coin][ix]
    test_amount = 10**(from_coin.decimals())
    amount *= test_amount
    with boa.env.prank(user):
        with boa.env.anchor():
            from_coin._mint_for_testing(user, amount)
            swap_w_d.exchange(ix, 1-ix, amount, 0)
            dy = swap_w_d.get_dy(0, 1, 10**6)
            p1 = 10**18 / dy
            p2 = swap_w_d.get_p() / 1e18
            assert approx(p1, p2, 0.04e-2 * 1.2)
