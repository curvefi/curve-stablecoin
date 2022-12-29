import boa
from ..conftest import approx
from hypothesis import given, settings
from hypothesis import strategies as st
from datetime import timedelta


@given(
        amounts=st.lists(st.integers(min_value=0, max_value=10**6 * 10**18), min_size=5, max_size=5),
        ns=st.lists(st.integers(min_value=-20, max_value=20), min_size=5, max_size=5),
        dns=st.lists(st.integers(min_value=0, max_value=20), min_size=5, max_size=5),
)
@settings(deadline=timedelta(seconds=1000))
def test_deposit_withdraw(amm, amounts, accounts, ns, dns, collateral_token, admin):
    deposits = {}
    with boa.env.prank(admin):
        for user, amount, n1, dn in zip(accounts, amounts, ns, dns):
            n2 = n1 + dn
            collateral_token._mint_for_testing(user, amount)
            if amount // (dn + 1) <= 100:
                with boa.reverts('Amount too low'):
                    amm.deposit_range(user, amount, n1, n2, True)
            else:
                amm.deposit_range(user, amount, n1, n2, True)
                deposits[user] = amount
                assert collateral_token.balanceOf(user) == 0

        for user, n1 in zip(accounts, ns):
            if user in deposits:
                if n1 >= 0:
                    assert approx(amm.get_y_up(user), deposits[user], 1e-6, 20)
                else:
                    assert amm.get_y_up(user) < deposits[user]  # price manipulation caused loss for user
            else:
                assert amm.get_y_up(user) == 0

        for user in accounts:
            if user in deposits:
                before = amm.get_sum_xy(user)
                amm.withdraw(user)
                after = amm.get_sum_xy(user)
                assert approx(before[1] - after[1], deposits[user], 1e-6, 20)
            else:
                with boa.reverts("No deposits"):
                    amm.withdraw(user)


def test_deposit_withdraw_1(amm, accounts, collateral_token, admin):
    with boa.env.anchor():
        test_deposit_withdraw.hypothesis.inner_test(amm, [10**6]+[0]*4, accounts, [0]*5, [0]*5, collateral_token, admin)
