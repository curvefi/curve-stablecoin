import boa
from hypothesis import given
from hypothesis import strategies as st

from tests.utils.constants import MAX_TICKS

MAX_N = 2**127 - 1
MIN_N = -(2**127) + 1  # <- not -2**127!
MAX_SPAN = MAX_TICKS - 1
DEPOSIT_AMOUNT = 10**6
MAX_SKIP_TICKS = 1024


@st.composite
def tick_ranges(draw, active_band):
    min_n1 = max(MIN_N, active_band - (MAX_SKIP_TICKS - 1))
    max_n1 = min(MAX_N, active_band + MAX_SKIP_TICKS)
    n1 = draw(st.integers(min_value=min_n1, max_value=max_n1))
    max_n2 = min(MAX_N, n1 + MAX_SPAN)
    n2 = draw(st.integers(min_value=n1, max_value=max_n2))
    return n1, n2


@given(data=st.data())
def test_ammpack_round_trip(amm, controller, data):
    active_band = amm.active_band()
    n1, n2 = data.draw(tick_ranges(active_band=active_band))

    with boa.env.anchor():
        amm.deposit_range(
            boa.env.eoa, DEPOSIT_AMOUNT, n1, n2, sender=controller.address
        )

        n1out, n2out = amm.read_user_tick_numbers(boa.env.eoa)
        assert n1out == n1
        assert n2out == n2
