import boa
from hypothesis import given, settings
from hypothesis import strategies as st
from datetime import timedelta
from math import exp
from ..conftest import approx


@given(
    amount=st.integers(min_value=1, max_value=10**6),
    ix=st.integers(min_value=0, max_value=1))
@settings(max_examples=100, deadline=timedelta(seconds=1000))
def test_price(swap_w_d, redeemable_coin, volatile_coin, accounts, amount, ix):
    user = accounts[0]
    assert swap_w_d.get_p() == 10**18
    from_coin = [redeemable_coin, volatile_coin][ix]
    amount *= 10**(from_coin.decimals())
    with boa.env.prank(user):
        from_coin._mint_for_testing(user, amount)
        swap_w_d.exchange(ix, 1-ix, amount, 0)
        dy = swap_w_d.get_dy(0, 1, 10**6)
        p1 = 10**18 / dy
        p2 = swap_w_d.get_p() / 1e18
        assert approx(p1, p2, 0.04e-2 * 1.2)


@given(
    amount=st.integers(min_value=1, max_value=10**5),
    ix=st.integers(min_value=0, max_value=1),
    dt0=st.integers(min_value=0, max_value=10**6),
    dt=st.integers(min_value=0, max_value=10**6))
@settings(max_examples=1000, deadline=timedelta(seconds=1000))
def test_ema(swap_w_d, redeemable_coin, volatile_coin, accounts, amount, ix, dt0, dt):
    user = accounts[0]
    from_coin = [redeemable_coin, volatile_coin][ix]
    amount *= 10**(from_coin.decimals())
    with boa.env.prank(user):
        from_coin._mint_for_testing(user, amount)
        boa.env.time_travel(dt0)
        swap_w_d.exchange(ix, 1-ix, amount, 0)
        # Time didn't pass yet
        p = swap_w_d.get_p()
        assert approx(swap_w_d.last_price(), p, 1e-5)
        assert approx(swap_w_d.price_oracle(), 10**18, 1e-5)
        boa.env.time_travel(dt)
        w = exp(-dt / 866)
        p1 = int(10**18 * w + p * (1 - w))
        assert approx(swap_w_d.price_oracle(), p1, 1e-5)
