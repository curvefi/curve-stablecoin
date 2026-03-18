import boa
import pytest
from hypothesis import given
from hypothesis import strategies as st
from tests.utils import mint_for_testing


from tests.utils.constants import DEAD_SHARES, MIN_SHARES_ALLOWED


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
    amounts = list(
        map(lambda x: x // 10 ** (18 - collateral_token.decimals()), amounts)
    )
    deposits = {}
    deposit_shares = {}
    precisions = {}
    with boa.env.prank(admin):
        for user, amount, n1, dn in zip(accounts, amounts, ns, dns):
            if amount <= dn:
                precisions[user] = DEAD_SHARES
            else:
                precisions[user] = DEAD_SHARES / (amount // (dn + 1)) + 1e-6
            n2 = n1 + dn

            y_per_band = amount * 10 ** (18 - collateral_token.decimals()) // (dn + 1)
            amount_too_low = y_per_band <= 100
            user_shares = []
            for n in range(n1, n2 + 1):
                if amount_too_low:
                    break
                total_y = amm.bands_y(n)
                # Total / user share
                s = amm.eval(f"self.total_shares[{n}]")
                ds = ((s + DEAD_SHARES) * y_per_band) // (total_y + 1)
                user_shares.append(ds)
                amount_too_low = amount_too_low or ds < MIN_SHARES_ALLOWED

            if amount_too_low:
                with boa.reverts("Amount too low"):
                    amm.deposit_range(user, amount, n1, n2)
            else:
                amm.deposit_range(user, amount, n1, n2)
                mint_for_testing(collateral_token, amm.address, amount)
                deposits[user] = amount
                deposit_shares[user] = user_shares
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
                amount_left_too_low = any(
                    (
                        share - (frac * share) // 10**18 != 0
                        and share - (frac * share) // 10**18 < MIN_SHARES_ALLOWED
                    )
                    for share in deposit_shares[user]
                )
                if amount_left_too_low:
                    with boa.reverts("Amount left too low"):
                        amm.withdraw(user, frac)
                else:
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
