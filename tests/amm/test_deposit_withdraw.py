import brownie
from brownie.test import given, strategy
from ..conftest import approx


@given(
        amounts=strategy('uint256[5]', min_value=0, max_value=10**6 * 10**18),
        ns=strategy('int256[5]', min_value=-20, max_value=20),
        dns=strategy('uint256[5]', min_value=0, max_value=20),
)
def test_deposit_withdraw(amm, amounts, accounts, ns, dns, collateral_token):
    admin = accounts[0]
    deposits = {}
    for user, amount, n1, dn in zip(accounts[1:6], amounts, ns, dns):
        n2 = n1 + dn
        collateral_token._mint_for_testing(user, amount)
        if amount // (dn + 1) <= 100:
            with brownie.reverts('Amount too low'):
                amm.deposit_range(user, amount, n1, n2, True, {'from': admin})
        else:
            amm.deposit_range(user, amount, n1, n2, True, {'from': admin})
            deposits[user] = amount
            assert collateral_token.balanceOf(user) == 0

    for user, n1 in zip(accounts[1:6], ns):
        if user in deposits:
            if n1 >= 0:
                assert approx(amm.get_y_up(user), deposits[user], 1e-6, 20)
            else:
                assert amm.get_y_up(user) < deposits[user]  # price manipulation caused loss for user
        else:
            assert amm.get_y_up(user) == 0

    for user in accounts[1:6]:
        if user in deposits:
            amm.withdraw(user, user, {'from': admin})
            assert approx(collateral_token.balanceOf(user), deposits[user], 1e-6, 20)
        else:
            with brownie.reverts("No deposits"):
                amm.withdraw(user, user, {'from': admin})
