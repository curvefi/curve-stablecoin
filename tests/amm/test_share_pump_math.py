from hypothesis import given, settings
from hypothesis import strategies as st


SHARE_PRICE = 10**18
DEAD_SHARES = 1000  # Amounts close to this numbers of shares will experience a small loss (down)


@given(
    q1=st.integers(min_value=1, max_value=100000000 * 10**18),  # Attacker
    q2=st.integers(min_value=1, max_value=10000 * 10**18)       # Victim
)
@settings(max_examples=15000)
def test_no_steal(q1, q2):
    # Protection based on Mixbytes, implemented in an OpenZeppelin audit elsewhere recently
    # Deposit
    s1 = q1 // SHARE_PRICE  # Doesn't matter how we've got to this one - could have been pumping
    s2 = q2 * (s1 + DEAD_SHARES) // (q1 + 1)
    if s1 == 0:
        return
    # Withdraw
    q2_out = s2 * (q1 + q2 + 1) // (s1 + s2 + DEAD_SHARES)
    qq = q1 + q2 - q2_out
    q1_out = s1 * (qq + 1) // (s1 + DEAD_SHARES)
    assert q1_out <= q1, "Attacker made money"
