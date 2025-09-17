import boa
import pytest
from hypothesis import given
from hypothesis import strategies as st
from ..utils import mint_for_testing


from tests.utils.constants import DEAD_SHARES


@given(
    amounts=st.lists(
        st.integers(min_value=0, max_value=10**6 * 10**18), min_size=5, max_size=5
    ),
    ns=st.lists(st.integers(min_value=-20, max_value=20), min_size=5, max_size=5),
    dns=st.lists(st.integers(min_value=0, max_value=20), min_size=5, max_size=5),
    fracs=st.lists(st.integers(min_value=0, max_value=10**18), min_size=5, max_size=5),
)
def test_deposit_withdraw(
    amm, amounts, accounts, ns, dns, fracs, collateral_token, admin
):
    deposits = {}
    precisions = {}
    with boa.env.prank(admin):
        for user, amount, n1, dn in zip(accounts, amounts, ns, dns):
            if amount <= dn:
                precisions[user] = DEAD_SHARES
            else:
                precisions[user] = DEAD_SHARES / (amount // (dn + 1)) + 1e-6
            n2 = n1 + dn
            if amount // (dn + 1) <= 100:
                with boa.reverts("Amount too low"):
                    amm.deposit_range(user, amount, n1, n2)
            else:
                amm.deposit_range(user, amount, n1, n2)
                mint_for_testing(collateral_token, amm.address, amount)
                deposits[user] = amount
                assert collateral_token.balanceOf(user) == 0

        for user, n1 in zip(accounts, ns):
            if user in deposits:
                if n1 >= 0:
                    assert amm.get_y_up(user) == pytest.approx(
                        deposits[user], rel=precisions[user], abs=25
                    )
                else:
                    assert (
                        amm.get_y_up(user) < deposits[user]
                    )  # price manipulation caused loss for user
            else:
                assert amm.get_y_up(user) == 0

        for user, frac, amount in zip(accounts, fracs, amounts):
            if user in deposits:
                before = amm.get_sum_xy(user)
                amm.withdraw(user, frac)
                after = amm.get_sum_xy(user)
                assert before[1] - after[1] == pytest.approx(
                    deposits[user] * frac / 1e18,
                    rel=precisions[user],
                    abs=25 + deposits[user] * precisions[user],
                )
            else:
                with boa.reverts("No deposits"):
                    amm.withdraw(user, frac)


def test_deposit_withdraw_1(amm, accounts, collateral_token, admin):
    with boa.env.anchor():
        test_deposit_withdraw.hypothesis.inner_test(
            amm,
            [10**6] + [0] * 4,
            accounts,
            [0] * 5,
            [0] * 5,
            [10**18] * 5,
            collateral_token,
            admin,
        )
