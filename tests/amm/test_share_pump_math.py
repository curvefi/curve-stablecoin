from hypothesis import given, settings
from hypothesis import strategies as st


SHARE_PRICE = 10**18
VIRTUAL_SHARES = 100000  # Amounts close to this numbers of shares will experience a small loss (down)


@given(
    q1=st.integers(min_value=1, max_value=100000000 * 10**18),  # Attacker
    q2=st.integers(min_value=1, max_value=10000 * 10**18)       # Victim
)
@settings(max_examples=15000)
def test_no_steal(q1, q2):
    # Deposit
    s1 = q1 // SHARE_PRICE
    s2 = q2 * s1 // q1
    if s1 == 0:
        return
    # Withdraw
    q2_out = s2 * (q1 + q2) // (s1 + s2 + VIRTUAL_SHARES)
    qq = q1 + q2 - q2_out
    q1_out = s1 * qq // (s1 + VIRTUAL_SHARES)
    assert q1_out <= q1, "Attacker made money"
