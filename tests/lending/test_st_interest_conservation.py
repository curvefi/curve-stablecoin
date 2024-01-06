import boa
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, run_state_machine_as_test, rule, invariant


DEAD_SHARES = 1000
MIN_RATE  = 10**15 / (365 * 86400)  # 0.1%
MAX_RATE  = 10**19 / (365 * 86400)  # 1000%


class StatefulLendBorrow(RuleBasedStateMachine):
    n = st.integers(min_value=5, max_value=50)
    amount = st.integers(min_value=0, max_value=2**256-1)
    c_amount = st.integers(min_value=0, max_value=2**256-1)
    user_id = st.integers(min_value=0, max_value=9)
    t = st.integers(min_value=0, max_value=86400 * 365)
    min_rate = st.integers(min_value=0, max_value=2**255 - 1)
    max_rate = st.integers(min_value=0, max_value=2**255 - 1)

    def __init__(self):
        super().__init__()
        self.collateral = self.collateral_token
        self.amm = self.market_amm
        self.controller = self.market_controller
        self.borrowed_precision = 10**(18 - self.borrowed_token.decimals())
        self.collateral_precision = 10**(18 - self.collateral_token.decimals())
        for u in self.accounts:
            with boa.env.prank(u):
                self.collateral_token.approve(self.controller.address, 2**256-1)
                self.borrowed_token.approve(self.controller.address, 2**256-1)
        self.debt_ceiling = 10**6 * 10**(self.borrowed_token.decimals())
        with boa.env.prank(self.accounts[0]):
            self.borrowed_token.approve(self.vault.address, 2**256 - 1)
            self.borrowed_token._mint_for_testing(self.accounts[0], self.debt_ceiling)
            self.vault.deposit(self.debt_ceiling)

    @rule(c_amount=c_amount, amount=amount, n=n, user_id=user_id)
    def create_loan(self, c_amount, amount, n, user_id):
        user = self.accounts[user_id]

        with boa.env.prank(user):
            if self.controller.loan_exists(user):
                with boa.reverts('Loan already created'):
                    self.controller.create_loan(c_amount, amount, n)
                return

            too_high = False
            try:
                self.controller.calculate_debt_n1(c_amount, amount, n)
            except Exception as e:
                too_high = 'Debt too high' in str(e)
            if too_high:
                with boa.reverts('Debt too high'):
                    self.controller.create_loan(c_amount, amount, n)
                return

            if self.controller.total_debt() + amount > self.debt_ceiling:
                if (
                        (self.controller.total_debt() + amount) * self.amm.get_rate_mul() > 2**256 - 1
                        or (c_amount * self.collateral_precision) * self.amm.get_p() > 2**256 - 1
                ):
                    with boa.reverts():
                        self.controller.create_loan(c_amount, amount, n)
                else:
                    with boa.reverts():
                        self.controller.create_loan(c_amount, amount, n)
                return

            if amount == 0:
                with boa.reverts('No loan'):
                    self.controller.create_loan(c_amount, amount, n)
                    # It's actually division by zero which happens
                return

            try:
                self.collateral._mint_for_testing(user, c_amount)
            except Exception:
                return  # Probably overflow

            if c_amount // n >= 2**128:
                with boa.reverts():
                    self.controller.create_loan(c_amount, amount, n)
                return

            if c_amount * self.collateral_precision // n <= 2 * DEAD_SHARES:
                try:
                    self.controller.create_loan(c_amount, amount, n)
                    return
                except Exception as e:
                    if ('Too deep' in str(e) and c_amount * self.collateral_precision * 3000 / (amount * self.borrowed_precision) < 1e-3) or 'Amount too low' in str(e):
                        return
                    else:
                        raise

            try:
                self.controller.create_loan(c_amount, amount, n)
            except Exception as e:
                if 'Too deep' in str(e) and (c_amount * 3000 * self.collateral_precision) / (amount * self.borrowed_precision) < 1e-3:
                    pass
                else:
                    if c_amount * self.collateral_precision // n <= (2**128 - 1) // DEAD_SHARES:
                        raise

    @rule(amount=amount, user_id=user_id)
    def repay(self, amount, user_id):
        user = self.accounts[user_id]
        to_repay = min(self.controller.debt(user), amount)
        user_balance = self.borrowed_token.balanceOf(user)
        if to_repay > user_balance:
            self.borrowed_token._mint_for_testing(user, to_repay - user_balance)

        with boa.env.prank(user):
            if amount == 0:
                self.controller.repay(amount, user)
                return

            if not self.controller.loan_exists(user):
                with boa.reverts("Loan doesn't exist"):
                    self.controller.repay(amount, user)
                return

            self.controller.repay(amount, user)

    @rule(c_amount=c_amount, user_id=user_id)
    def add_collateral(self, c_amount, user_id):
        user = self.accounts[user_id]

        with boa.env.prank(user):
            try:
                self.collateral._mint_for_testing(user, c_amount)
            except Exception:
                return  # Probably overflow

            if c_amount == 0:
                self.controller.add_collateral(c_amount, user)
                return

            if not self.controller.loan_exists(user):
                with boa.reverts("Loan doesn't exist"):
                    self.controller.add_collateral(c_amount, user)
                return

            if (c_amount + self.amm.get_sum_xy(user)[1]) * self.collateral_precision * self.amm.get_p() > 2**256 - 1:
                with boa.reverts():
                    self.controller.add_collateral(c_amount, user)
                return

            try:
                self.controller.add_collateral(c_amount, user)
            except Exception:
                if (c_amount + self.amm.get_sum_xy(user)[1]) * self.collateral_precision < (2**128 - 1) // DEAD_SHARES:
                    raise

    @rule(c_amount=c_amount, amount=amount, user_id=user_id)
    def borrow_more(self, c_amount, amount, user_id):
        user = self.accounts[user_id]

        with boa.env.prank(user):
            if amount == 0:
                self.controller.borrow_more(c_amount, amount)
                return

            try:
                self.collateral._mint_for_testing(user, c_amount)
            except Exception:
                return  # Probably overflow

            if not self.controller.loan_exists(user):
                with boa.reverts("Loan doesn't exist"):
                    self.controller.borrow_more(c_amount, amount)
                return

            final_debt = self.controller.debt(user) + amount
            x, y = self.amm.get_sum_xy(user)
            assert x == 0
            final_collateral = y + c_amount
            n1, n2 = self.amm.read_user_tick_numbers(user)
            n = n2 - n1 + 1

            too_high = False
            try:
                self.controller.calculate_debt_n1(final_collateral, final_debt, n)
            except Exception as e:
                too_high = 'Debt too high' in str(e)
            if too_high:
                with boa.reverts('Debt too high'):
                    self.controller.borrow_more(c_amount, amount)
                return

            if self.controller.total_debt() + amount > self.debt_ceiling:
                if (self.controller.total_debt() + amount) * self.collateral_precision * self.amm.get_rate_mul() > 2**256 - 1:
                    with boa.reverts():
                        self.controller.borrow_more(c_amount, amount)
                else:
                    with boa.reverts():
                        self.controller.borrow_more(c_amount, amount)
                return

            if final_collateral * self.collateral_precision // n > (2**128 - 1) // DEAD_SHARES:
                with boa.reverts():
                    self.controller.borrow_more(c_amount, amount)
                return

            self.controller.borrow_more(c_amount, amount)

    @rule(t=t)
    def time_travel(self, t):
        boa.env.time_travel(t)

    @rule(min_rate=min_rate, max_rate=max_rate)
    def change_rate(self, min_rate, max_rate):
        with boa.env.prank(self.admin):
            if (min_rate > max_rate or min_rate < MIN_RATE or max_rate < MIN_RATE
                or min_rate > MAX_RATE or max_rate > MAX_RATE
            ):            
                with boa.reverts():
                    self.market_mpolicy.set_default_rates(min_rate, max_rate)
            else:
                self.market_mpolicy.set_default_rates(min_rate, max_rate)

    @invariant()
    def sum_of_debts(self):
        S = sum(self.controller.debt(u) for u in self.accounts)
        T = self.controller.total_debt()
        assert abs(S - T) <= len(self.accounts)
        if S == 0:
            assert T == 0

    @invariant()
    def debt_payable(self):
        with boa.env.prank(self.admin):
            supply = self.borrowed_token.totalSupply()
            b = self.borrowed_token.balanceOf(self.controller)
            debt = self.controller.total_debt()
            assert debt + 10 >= supply - b  # Can have error of 1 (rounding) at most per step (and 10 stateful steps)


def test_stateful_lendborrow(vault, market_amm, market_controller, market_mpolicy, collateral_token, borrowed_token, accounts, admin):
    StatefulLendBorrow.TestCase.settings = settings(max_examples=2000, stateful_step_count=10)
    for k, v in locals().items():
        setattr(StatefulLendBorrow, k, v)
    run_state_machine_as_test(StatefulLendBorrow)


def test_borrow_not_reverting(vault, market_amm, market_controller, market_mpolicy, collateral_token, borrowed_token, accounts, admin):
    for k, v in locals().items():
        setattr(StatefulLendBorrow, k, v)
    state = StatefulLendBorrow()
    state.debt_payable()
    state.sum_of_debts()
    state.time_travel(t=0)
    state.debt_payable()
    state.sum_of_debts()
    state.create_loan(amount=1, c_amount=28303, n=5, user_id=0)
    state.debt_payable()
    state.sum_of_debts()
    state.borrow_more(amount=1, c_amount=11229318108390940992, user_id=0)
    state.teardown()
