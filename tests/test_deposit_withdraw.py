import brownie
from brownie.test import given, strategy
from .conftest import approx


@given(
        amounts=strategy('uint256[5]', min_value=10**9, max_value=10**6 * 10**18),
        ns=strategy('int256[5]', min_value=-20, max_value=20),
        dns=strategy('uint256[5]', min_value=0, max_value=20),
)
def test_deposit_withdraw(amm, amounts, accounts, ns, dns, collateral_token):
    admin = accounts[0]
    n0 = amm.active_band()
    deposits = {}
    for user, amount, n1, dn in zip(accounts[1:6], amounts, ns, dns):
        n2 = n1 + dn
        collateral_token._mint_for_testing(user, amount)
        if n1 <= n0:
            with brownie.reverts('Deposits should be below current band'):
                amm.deposit_range(user, amount, n1, n2, True, {'from': admin})
        else:
            if amount // (dn + 1) == 0:
                with brownie.reverts('Amount too low'):
                    amm.deposit_range(user, amount, n1, n2, True, {'from': admin})
            else:
                amm.deposit_range(user, amount, n1, n2, True, {'from': admin})
                deposits[user] = amount
                assert collateral_token.balanceOf(user) == 0

    for user in accounts[1:6]:
        if user in deposits:
            assert approx(amm.get_y_up(user), deposits[user], 1e-6)
        else:
            assert amm.get_y_up(user) == 0

    if False:
        for user in accounts[1:6]:
            if user in deposits:
                amm.withdraw(user, user, {'from': admin})
                assert collateral_token.balanceOf(user) == deposits[user]
            else:
                with brownie.reverts("No deposits"):
                    amm.withdraw(user, user, {'from': admin})
