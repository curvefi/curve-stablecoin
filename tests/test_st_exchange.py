from brownie.test import strategy


class StatefulExchange:
    amounts = strategy('uint256[5]', min_value=0, max_value=10**6 * 10**18)
    ns = strategy('int256[5]', min_value=1, max_value=20)
    dns = strategy('uint256[5]', min_value=0, max_value=20)
    amount = strategy('uint256', max_value=10**9 * 10**6)
    pump = strategy('bool')
    user_id = strategy('uint256', max_value=4)

    def __init__(self, amm, collateral_token, borrowed_token, accounts):
        self.amm = amm
        self.collateral_token = collateral_token
        self.borrowed_token = borrowed_token
        self.accounts = accounts[1:6]
        self.admin = accounts[0]

    def initialize(self, amounts, ns, dns):
        for user, amount, n1, dn in zip(self.accounts, amounts, ns, dns):
            n2 = n1 + dn
            self.collateral_token._mint_for_testing(user, amount)
            try:
                self.amm.deposit_range(user, amount, n1, n2, True, {'from': self.admin})
            except Exception as e:
                if 'Amount too low' in str(e):
                    assert amount // (dn + 1) == 0
                else:
                    raise
        self.total_deposited = sum(self.amm.bands_y(n) for n in range(42))

    def rule_exchange(self, amount, pump, user_id):
        u = self.accounts[user_id]
        if pump:
            i = 0
            j = 1
            in_token = self.borrowed_token
        else:
            i = 1
            j = 0
            in_token = self.collateral_token
        u_amount = in_token.balanceOf(u)
        if amount > u_amount:
            in_token._mint_for_testing(u, amount - u_amount)
        self.amm.exchange(i, j, amount, 0, {'from': u})

    def invariant_amm_solvent(self):
        X = sum(self.amm.bands_x(n) for n in range(42))
        Y = sum(self.amm.bands_y(n) for n in range(42))
        assert self.borrowed_token.balanceOf(self.amm) * 10**(18 - 6) >= X
        assert self.collateral_token.balanceOf(self.amm) >= Y

    def invariant_dy_back(self):
        n = self.amm.active_band()
        to_swap = self.total_deposited * 10
        left_in_amm = sum(self.amm.bands_y(n) for n in range(42))
        if n < 50:
            dx, dy = self.amm.get_dxdy(1, 0, to_swap)
            assert dx >= self.total_deposited - left_in_amm  # With fees, AMM will have more

    # def teardown(self):
    #     # Trade back and do the check
    #     pass


def test_exchange(accounts, amm, collateral_token, borrowed_token, state_machine):
    state_machine(StatefulExchange, amm, collateral_token, borrowed_token, accounts)
