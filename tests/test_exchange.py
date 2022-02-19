from brownie.test import given, strategy


@given(
        amounts=strategy('uint256[5]', min_value=10**8, max_value=10**6 * 10**18),
        ns=strategy('int256[5]', min_value=1, max_value=20),
        dns=strategy('uint256[5]', min_value=0, max_value=20),
)
def test_dxdy_limits(amm, amounts, accounts, ns, dns, collateral_token):
    admin = accounts[0]

    for user, amount, n1, dn in zip(accounts[1:6], amounts, ns, dns):
        n2 = n1 + dn
        collateral_token._mint_for_testing(user, amount)
        amm.deposit_range(user, amount, n1, n2, True, {'from': admin})
        assert collateral_token.balanceOf(user) == 0

    x, y = amm.get_dxdy(0, 1, 0)
    assert x == 0 and y == 0
