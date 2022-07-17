from brownie.test import strategy


class AdiabaticTrader:
    oracle_step = strategy('int256', min_value=-10**16, max_value=10**16)
    collateral_amount = strategy('uint256', min_value=10**10, max_value=10**18 * 10**6 // 3000)  # Borrow max?
    amount_fraction = strategy('uint256', max_value=11 * 10**17)
    is_pump = strategy('bool')
    n = strategy('uint256', min_value=5, max_value=50)
    t = strategy('uint256', max_value=86400)
    rate = strategy('uint256', max_value=int(1e18 * 0.2 / 365 / 86400))

    def __init__(self, chain, amm, controller, monetary_policy, collateral_token, borrowed_token, oracle, accounts):
        self.chain = chain
        self.monetary_policy = monetary_policy
        self.amm = amm
        self.controller = controller
        self.collateral = collateral_token
        self.stablecoin = borrowed_token
        self.accounts = accounts
        self.oracle = oracle
        monetary_policy.set_rate(int(1e18 * 0.04 / 365 / 86400), {'from': accounts[0]})

    def initialize(self, collateral_amount, n):
        user = self.accounts[0]
        self.collateral._mint_for_testing(user, collateral_amount)
        # XXX we need to test max_borrowable separately
        loan_amount = self.controller.max_borrowable(collateral_amount, n)
        self.controller.create_loan(collateral_amount, loan_amount, n, {'from': user})
        self.stablecoin.transfer(self.accounts[1], loan_amount, {'from': user})
        self.loan_amount = loan_amount
        self.collateral_amount = collateral_amount

    def trade_to_price(self, p):
        user = self.accounts[1]
        self.controller.collect_fees({'from': user})
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

    def rule_time_travel(self, t):
        self.chain.sleep(t)

    def rule_change_rate(self, rate):
        self.monetary_policy.set_rate(rate, {'from': self.accounts[0]})

    def invariant_health(self):
        assert self.controller.health(self.accounts[0]) > 0


def test_adiabatic_follow(chain, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, PriceOracle, accounts, state_machine):
    state_machine(AdiabaticTrader, chain, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, PriceOracle, accounts,
                  settings={'max_examples': 50, 'stateful_step_count': 50})


def test_approval_worked(chain, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, PriceOracle, accounts, state_machine):
    state = AdiabaticTrader(chain, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, PriceOracle, accounts)
    state.initialize(collateral_amount=10000000000, n=7)
    state.rule_shift_oracle(oracle_step=-5581384867293334)
    state.rule_shift_oracle(oracle_step=-6965451302984162)


def test_shift_oracle_fail(chain, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, PriceOracle, accounts, state_machine):
    # Fail which was due to rounding eror in get_amount_for_price
    state = AdiabaticTrader(chain, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, PriceOracle, accounts)
    state.initialize(collateral_amount=10000000257, n=5)
    state.rule_change_rate(rate=1)
    state.rule_change_rate(rate=0)
    state.rule_change_rate(rate=0)
    state.rule_shift_oracle(oracle_step=-7545700784685381)
    state.rule_shift_oracle(oracle_step=-9113745346295811)
    state.rule_shift_oracle(oracle_step=0)
