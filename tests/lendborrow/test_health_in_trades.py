from brownie.test import strategy


class AdiabaticTrader:
    oracle_step = strategy('int256', min_value=-10**16, max_value=10**16)
    collateral_amount = strategy('uint256', min_value=10**10, max_value=10**18 * 10**6 // 3000)  # Borrow max?
    amount_fraction = strategy('uint256', max_value=11 * 10**17)
    is_pump = strategy('bool')
    n = strategy('uint256', min_value=5, max_value=50)

    def __init__(self, amm, controller, collateral_token, borrowed_token, oracle, accounts):
        self.amm = amm
        self.controller = controller
        self.collateral = collateral_token
        self.stablecoin = borrowed_token
        self.accounts = accounts
        self.oracle = oracle
        for u in accounts[0:2]:
            collateral_token.approve(controller, 2**256-1, {'from': u})
            borrowed_token.approve(controller, 2**256-1, {'from': u})

    def initialize(self, collateral_amount, n):
        user = self.accounts[0]
        self.collateral._mint_for_testing(user, collateral_amount)
        A = self.amm.A()
        loan_amount = int(((A - 1) / A)**0.5 * 0.94 * 3000 * collateral_amount / 1e12)
        self.controller.create_loan(collateral_amount, loan_amount, n, {'from': user})
        self.stablecoin.transfer(self.accounts[1], loan_amount, {'from': user})
        self.loan_amount = loan_amount
        self.collateral_amount = collateral_amount

    def trade_to_price(self, p):
        user = self.accounts[1]
        amount, is_pump = self.amm.get_amount_for_price(p)
        if amount > 0:
            if is_pump:
                self.amm.exchange(0, 1, amount, 0, {'from': user})
            else:
                self.collateral._mint_for_testing(user, amount)
                self.amm.exchange(1, 0, amount, 0, {'from': user})

    def rule_shift_oracle(self, oracle_step):
        self.trade_to_price(self.oracle.price())
        p = self.oracle.price() * (10**18 + oracle_step) // 10**18
        self.oracle.set_price(p, {'from': self.accounts[0]})
        self.trade_to_price(p)

    def rule_random_trade(self, amount_fraction, is_pump):
        user = self.accounts[0]
        if is_pump:
            amount = min(self.loan_amount * amount_fraction // 10**18, self.stablecoin.balanceOf(user))
            self.amm.exchange(0, 1, amount, 0, {'from': user})
        else:
            amount = self.collateral_amount * amount_fraction // 10**18
            self.collateral._mint_for_testing(user, amount)
            self.amm.exchange(1, 0, amount, 0, {'from': user})

    def invariant_health(self):
        assert self.controller.health(self.accounts[0]) > 0


def test_adiabatic_follow(market_amm, market_controller, collateral_token, stablecoin, PriceOracle, accounts, state_machine):
    state_machine(AdiabaticTrader, market_amm, market_controller, collateral_token, stablecoin, PriceOracle, accounts,
                  settings={'max_examples': 20, 'stateful_step_count': 100})
