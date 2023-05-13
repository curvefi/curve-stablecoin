import boa
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, run_state_machine_as_test, rule, invariant


DEAD_SHARES = 1000


class StatefulLendBorrow(RuleBasedStateMachine):
    n = st.integers(min_value=5, max_value=50)
    amount = st.integers(min_value=0, max_value=2**256-1)
    c_amount = st.integers(min_value=0, max_value=2**256-1)
    user_id = st.integers(min_value=0, max_value=9)
    t = st.integers(min_value=0, max_value=86400 * 365)
    rate = st.integers(min_value=0, max_value=2**255 - 1)  # Negative is probably not good btw

    def __init__(self):
        super().__init__()
        self.collateral = self.collateral_token
        self.amm = self.market_amm
        self.controller = self.market_controller
        self.debt_ceiling = self.controller_factory.debt_ceiling(self.controller.address)
        for u in self.accounts:
            with boa.env.prank(u):
                self.collateral_token.approve(self.controller.address, 2**256-1)
                self.stablecoin.approve(self.controller.address, 2**256-1)
        with boa.env.prank(self.admin):
            self.monetary_policy.set_rate(int(1e18 * 0.04 / 365 / 86400))

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
                        or c_amount * self.amm.get_p() > 2**256 - 1
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

            if c_amount // n <= 2 * DEAD_SHARES:
                try:
                    self.controller.create_loan(c_amount, amount, n)
                    return
                except Exception as e:
                    if ('Too deep' in str(e) and c_amount * 3000 / amount < 1e-3) or 'Amount too low' in str(e):
                        return
                    else:
                        raise

            try:
                self.controller.create_loan(c_amount, amount, n)
            except Exception as e:
                if 'Too deep' in str(e) and c_amount * 3000 / amount < 1e-3:
                    pass
                else:
                    if c_amount // n <= (2**128 - 1) // DEAD_SHARES:
                        raise

    @rule(amount=amount, user_id=user_id)
    def repay(self, amount, user_id):
        user = self.accounts[user_id]

        with boa.env.prank(user):
            if amount == 0:
                self.controller.repay(amount, user)
                return

            if not self.controller.loan_exists(user):
                with boa.reverts("Loan doesn't exist"):
                    self.controller.repay(amount, user)
                return

            # When we have interest - need to have admin fees claimed to have enough in circulation
            self.controller.collect_fees()
            # And we need to transfer them to us if necessary
            diff = self.controller.debt(user) - self.stablecoin.balanceOf(user)
            if diff > 0:
                with boa.env.prank(self.accounts[0]):
                    self.stablecoin.transfer(user, diff)

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

            if (c_amount + self.amm.get_sum_xy(user)[1]) * self.amm.get_p() > 2**256 - 1:
                with boa.reverts():
                    self.controller.add_collateral(c_amount, user)
                return

            try:
                self.controller.add_collateral(c_amount, user)
            except Exception:
                if (c_amount + self.amm.get_sum_xy(user)[1]) < (2**128 - 1) // DEAD_SHARES:
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
                if (self.controller.total_debt() + amount) * self.amm.get_rate_mul() > 2**256 - 1:
                    with boa.reverts():
                        self.controller.borrow_more(c_amount, amount)
                else:
                    with boa.reverts():
                        self.controller.borrow_more(c_amount, amount)
                return

            if final_collateral * self.amm.get_p() > 2**256 - 1:
                with boa.reverts():
                    self.controller.borrow_more(c_amount, amount)
                return

            self.controller.borrow_more(c_amount, amount)

    @rule(t=t)
    def time_travel(self, t):
        boa.env.time_travel(t)

    @rule(rate=rate)
    def change_rate(self, rate):
        with boa.env.prank(self.admin):
            self.monetary_policy.set_rate(rate)

    @invariant()
    def sum_of_debts(self):
        assert abs(sum(self.controller.debt(u) for u in self.accounts) - self.controller.total_debt()) <= len(self.accounts)

    @invariant()
    def debt_payable(self):
        with boa.env.prank(self.admin):
            self.controller.collect_fees()
            supply = self.stablecoin.totalSupply()
            b = self.stablecoin.balanceOf(self.controller)
            debt = self.controller.total_debt()
            assert debt == supply - b


def test_stateful_lendborrow(controller_factory, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, accounts, admin):
    StatefulLendBorrow.TestCase.settings = settings(max_examples=100, stateful_step_count=10)
    for k, v in locals().items():
        setattr(StatefulLendBorrow, k, v)
    run_state_machine_as_test(StatefulLendBorrow)


def test_rate_too_high(controller_factory, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, accounts, admin):
    for k, v in locals().items():
        setattr(StatefulLendBorrow, k, v)
    with boa.env.anchor():
        state = StatefulLendBorrow()
        state.change_rate(rate=19298681539552733520784193015473224553355594960504706685844695763378761203935)
        state.time_travel(100000)
        # rate clipping
        state.amm.get_rate_mul()


def test_unexpected_revert(controller_factory, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, accounts, admin):
    for k, v in locals().items():
        setattr(StatefulLendBorrow, k, v)
    with boa.env.anchor():
        state = StatefulLendBorrow()
        state.create_loan(amount=28150, c_amount=5384530291638384907, n=8, user_id=1)
        state.time_travel(t=31488)
        state.repay(amount=39777, user_id=1)


def test_no_revert_reason(controller_factory, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, accounts, admin):
    for k, v in locals().items():
        setattr(StatefulLendBorrow, k, v)
    with boa.env.anchor():
        state = StatefulLendBorrow()
        state.create_loan(amount=1, c_amount=1, n=5, user_id=0)


def test_too_deep(controller_factory, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, accounts, admin):
    for k, v in locals().items():
        setattr(StatefulLendBorrow, k, v)
    with boa.env.anchor():
        state = StatefulLendBorrow()
        state.create_loan(amount=13119, c_amount=48, n=43, user_id=0)
        state.create_loan(amount=34049, c_amount=48388, n=18, user_id=1)
        state.create_loan(amount=10161325728155098164, c_amount=4156800770, n=50, user_id=2)


def test_overflow(controller_factory, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, accounts, admin):
    for k, v in locals().items():
        setattr(StatefulLendBorrow, k, v)
    state = StatefulLendBorrow()
    state.debt_payable()
    state.sum_of_debts()
    state.time_travel(t=0)
    state.debt_payable()
    state.sum_of_debts()
    state.time_travel(t=0)
    state.debt_payable()
    state.sum_of_debts()
    state.borrow_more(amount=102598604287098624639570500830661495567, c_amount=12171265979771193868, user_id=0)
    state.debt_payable()
    state.sum_of_debts()
    state.create_loan(amount=1, c_amount=5295, n=5, user_id=0)
    state.debt_payable()
    state.sum_of_debts()
    state.create_loan(amount=1, c_amount=180378547575685118, n=5, user_id=1)
    state.debt_payable()
    state.sum_of_debts()
    state.add_collateral(c_amount=1701411834604692317136494489587668075, user_id=0)
    state.teardown()
