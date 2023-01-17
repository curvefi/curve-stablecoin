import boa
from boa.vyper.contract import BoaError
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, run_state_machine_as_test, rule, invariant
from datetime import timedelta


# Variables and methods to check
# * A

# * liquidate
# * self_liquidate
# * set_amm_fee
# * set_amm_admin_fee
# * set_debt_ceiling
# * set_borrowing_discounts
# * collect AMM fees


class BigFuzz(RuleBasedStateMachine):
    collateral_amount = st.integers(min_value=0, max_value=10**18 * 10**6 // 3000)
    loan_amount = st.integers(min_value=0, max_value=10**18 * 10**6 // 3000)
    n = st.integers(min_value=5, max_value=50)
    ratio = st.floats(min_value=0, max_value=2)

    is_pump = st.booleans()
    rate = st.integers(min_value=0, max_value=int(1e18 * 0.2 / 365 / 86400))
    oracle_step = st.floats(min_value=-0.01, max_value=0.01)

    user_id = st.integers(min_value=0, max_value=9)
    liquidator_id = st.integers(min_value=0, max_value=9)
    time_shift = st.integers(min_value=1, max_value=30 * 86400)

    def __init__(self):
        super().__init__()
        self.A = self.market_amm.A()
        self.debt_ceiling = self.controller_factory.debt_ceiling(self.market_controller.address)
        self.fees = 0

    # Auxiliary methods #
    def collect_fees(self):
        fees = self.stablecoin.balanceOf(self.accounts[0])
        self.market_controller.collect_fees()
        fees = self.stablecoin.balanceOf(self.accounts[0]) - fees
        self.fees += fees

    def get_stablecoins(self, user):
        with boa.env.prank(self.accounts[0]):
            self.collect_fees()
            if user != self.accounts[0]:
                amount = self.stablecoin.balanceOf(self.accounts[0])
                if amount > 0:
                    self.stablecoin.transfer(user, amount)

    def remove_stablecoins(self, user):
        if user != self.accounts[0]:
            with boa.env.prank(user):
                amount = self.stablecoin.balanceOf(user)
                if amount > 0:
                    self.stablecoin.transfer(self.accounts[0], amount)

    def check_debt_ceiling(self, amount):
        return self.market_controller.total_debt() + amount <= self.debt_ceiling

    # Borrowing and returning #
    @rule(y=collateral_amount, n=n, uid=user_id, ratio=ratio)
    def deposit(self, y, n, ratio, uid):
        user = self.accounts[uid]
        debt = int(ratio * 3000 * y)
        with boa.env.prank(user):
            self.collateral_token._mint_for_testing(user, y)
            max_debt = self.market_controller.max_borrowable(y, n)
            if not self.check_debt_ceiling(debt):
                with boa.reverts():
                    self.market_controller.create_loan(y, debt, n)
                return
            if (debt > max_debt or y // n <= 100 or debt == 0
                    or self.market_controller.loan_exists(user)):
                if debt < max_debt / (0.9999 - 20/(y + 40)):
                    try:
                        self.market_controller.create_loan(y, debt, n)
                    except Exception:
                        pass
                else:
                    try:
                        self.market_controller.create_loan(y, debt, n)
                    except Exception:
                        return
                    assert debt < max_debt * (self.A / (self.A - 1))**0.4
                return
            else:
                self.market_controller.create_loan(y, debt, n)
            self.stablecoin.transfer(self.accounts[0], debt)

    @rule(ratio=ratio, uid=user_id)
    def repay(self, ratio, uid):
        user = self.accounts[uid]
        debt = self.market_controller.debt(user)
        amount = int(ratio * debt)
        self.get_stablecoins(user)
        with boa.env.prank(user):
            if debt == 0 and amount > 0:
                with boa.reverts(fail="insufficient funds"):
                    self.market_controller.repay(amount, user)
            else:
                if amount > 0 and (
                        (amount >= debt and (debt > self.stablecoin.balanceOf(user) + self.market_amm.get_sum_xy(user)[0]))
                        or (amount < debt and (amount > self.stablecoin.balanceOf(user)))):
                    with boa.reverts(fail="insufficient funds"):
                        self.market_controller.repay(amount, user)
                else:
                    self.market_controller.repay(amount, user)
        self.remove_stablecoins(user)

    @rule(y=collateral_amount, uid=user_id)
    def add_collateral(self, y, uid):
        user = self.accounts[uid]
        exists = self.market_controller.loan_exists(user)
        if exists:
            n1, n2 = self.market_amm.read_user_tick_numbers(user)
            n0 = self.market_amm.active_band()
        self.collateral_token._mint_for_testing(user, y)

        with boa.env.prank(user):
            if (exists and n1 > n0 and self.market_amm.p_oracle_up(n1) < self.market_amm.price_oracle()) or y == 0:
                self.market_controller.add_collateral(y, user)
            else:
                with boa.reverts():
                    self.market_controller.add_collateral(y, user)

    @rule(y=collateral_amount, uid=user_id)
    def remove_collateral(self, y, uid):
        user = self.accounts[uid]
        user_collateral, user_stablecoin, debt, N = self.market_controller.user_state(user)
        if debt > 0:
            n1, n2 = self.market_amm.read_user_tick_numbers(user)
            n0 = self.market_amm.active_band()

        with boa.env.prank(user):
            if (debt > 0 and n1 > n0) or y == 0:
                before = self.collateral_token.balanceOf(user)
                min_collateral = self.market_controller.min_collateral(debt, N)
                try:
                    self.market_controller.remove_collateral(y)
                except Exception:
                    if user_stablecoin > 0:
                        return
                    if (user_collateral - y) // N <= 100:
                        return
                    if user_collateral - y > min_collateral:
                        raise
                    else:
                        return
                after = self.collateral_token.balanceOf(user)
                assert after - before == y
            else:
                with boa.reverts():
                    self.market_controller.remove_collateral(y)

    @rule(y=collateral_amount, uid=user_id, ratio=ratio)
    def borrow_more(self, y, ratio, uid):
        user = self.accounts[uid]
        self.collateral_token._mint_for_testing(user, y)

        with boa.env.prank(user):
            if not self.market_controller.loan_exists(user):
                with boa.reverts():
                    self.market_controller.borrow_more(y, 1)

            else:
                sx, sy = self.market_amm.get_sum_xy(user)
                n1, n2 = self.market_amm.read_user_tick_numbers(user)
                n = n2 - n1 + 1
                amount = int(self.market_amm.price_oracle() * (sy + y) / 1e18 * ratio)
                final_debt = self.market_controller.debt(user) + amount

                if not self.check_debt_ceiling(amount):
                    with boa.reverts():
                        self.market_controller.borrow_more(y, amount)
                    return

                if sx == 0 or amount == 0:
                    max_debt = self.market_controller.max_borrowable(sy + y, n)
                    if final_debt > max_debt and amount > 0:
                        if final_debt < max_debt / (0.9999 - 20/(y + 40) - 1e-9):
                            try:
                                self.market_controller.borrow_more(y, amount)
                            except Exception:
                                pass
                        else:
                            with boa.reverts():
                                self.market_controller.borrow_more(y, amount)
                    else:
                        self.market_controller.borrow_more(y, amount)

                else:
                    with boa.reverts():
                        self.market_controller.borrow_more(y, amount)

    # Trading
    def trade_to_price(self, p):
        user = self.accounts[0]
        with boa.env.prank(user):
            self.collect_fees()
            amount, is_pump = self.market_amm.get_amount_for_price(p)
            if amount > 0:
                if is_pump:
                    self.market_amm.exchange(0, 1, amount, 0)
                else:
                    self.collateral_token._mint_for_testing(user, amount)
                    self.market_amm.exchange(1, 0, amount, 0)

    @rule(r=ratio, is_pump=is_pump, uid=user_id)
    def trade(self, r, is_pump, uid):
        user = self.accounts[uid]
        self.get_stablecoins(user)
        with boa.env.prank(user):
            if is_pump:
                b = self.stablecoin.balanceOf(user)
                amount = int(r * b)
                if r <= 1:
                    amount = min(amount, b)  # For floating point errors
                    self.market_amm.exchange(0, 1, amount, 0)
                else:
                    try:
                        self.market_amm.exchange(0, 1, amount, 0)
                    except BoaError:
                        # We may have not enough coins, but no exception if
                        # we are maxed out with the swap size
                        pass
            else:
                amount = int(r * self.collateral_token.totalSupply())
                self.collateral_token._mint_for_testing(user, amount)
                self.market_amm.exchange(1, 0, amount, 0)
        self.remove_stablecoins(user)

    # Liquidations
    @rule()
    def self_liquidate_and_health(self):
        for user in self.accounts:
            try:
                health = self.market_controller.health(user)
            except BoaError:
                # Too deep
                return
            if self.market_controller.loan_exists(user) and health <= 0:
                self.get_stablecoins(user)
                with boa.env.prank(user):
                    self.market_controller.liquidate(user, 0)
                self.remove_stablecoins(user)
                assert not self.market_controller.loan_exists(user)
                with boa.reverts():
                    self.market_controller.health(user)

    @rule(uid=user_id, luid=liquidator_id)
    def liquidate(self, uid, luid):
        user = self.accounts[uid]
        liquidator = self.accounts[luid]
        self.get_stablecoins(liquidator)
        if not self.market_controller.loan_exists(user):
            with boa.env.prank(liquidator):
                with boa.reverts():
                    self.market_controller.liquidate(user, 0)
        else:
            health_limit = self.market_controller.liquidation_discount()
            try:
                health = self.market_controller.health(user, True)
            except Exception as e:
                assert 'Too deep' in str(e)
            with boa.env.prank(liquidator):
                if health >= health_limit:
                    with boa.reverts():
                        self.market_controller.liquidate(user, 0)
                else:
                    self.market_controller.liquidate(user, 0)
                    with boa.reverts():
                        self.market_controller.health(user)
        self.remove_stablecoins(liquidator)

    # Other
    @rule(dp=oracle_step)
    def shift_oracle(self, dp):
        # Oracle shift is done via adiabatic trading which shouldn't decrease health
        if dp != 0:
            p0 = self.price_oracle.price()
            self.trade_to_price(p0)
            p = int(p0 * (1 + dp))
            with boa.env.prank(self.admin):
                self.price_oracle.set_price(p)
            self.trade_to_price(p)

    @rule(rate=rate)
    def rule_change_rate(self, rate):
        with boa.env.prank(self.admin):
            self.monetary_policy.set_rate(rate)

    @rule(dt=time_shift)
    def time_travel(self, dt):
        boa.env.time_travel(dt)

    @invariant()
    def debt_supply(self):
        self.collect_fees()
        total_debt = self.market_controller.total_debt()
        assert total_debt == self.stablecoin.totalSupply() - self.stablecoin.balanceOf(self.market_controller.address)
        assert abs(sum(self.market_controller.debt(u) for u in self.accounts) - total_debt) <= 10
        # 10 accounts = 10 wei error?


def test_big_fuzz(
        controller_factory, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, price_oracle, accounts, admin):
    BigFuzz.TestCase.settings = settings(max_examples=2500, stateful_step_count=20, deadline=timedelta(seconds=1000))
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    run_state_machine_as_test(BigFuzz)


def test_noraise(
        controller_factory, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, price_oracle, accounts, admin):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    with boa.env.anchor():
        state = BigFuzz()
        state.debt_supply()
        state.add_collateral(uid=0, y=0)
        state.debt_supply()
        state.shift_oracle(dp=0.0078125)
        state.debt_supply()
        state.deposit(n=5, ratio=1.0, uid=0, y=505)


def test_noraise_2(
        controller_factory, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, price_oracle, accounts, admin):
    # This is due to evmdiv working not like floor div (fixed)
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    with boa.env.anchor():
        state = BigFuzz()
        state.shift_oracle(dp=2.3841130314394837e-09)
        state.deposit(n=5, ratio=0.9340958492675753, uid=0, y=4063)


def test_exchange_fails(
        controller_factory, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, price_oracle, accounts, admin):
    # This is due to evmdiv working not like floor div (fixed)
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    with boa.env.anchor():
        state = BigFuzz()
        state.debt_supply()
        state.add_collateral(uid=0, y=0)
        state.debt_supply()
        state.shift_oracle(dp=0.0)
        state.debt_supply()
        state.time_travel(dt=6)
        state.debt_supply()
        state.deposit(n=5, ratio=6.103515625e-05, uid=1, y=14085)
        state.debt_supply()
        state.deposit(n=5, ratio=1.199379084937393e-07, uid=0, y=26373080523014146049)
        state.debt_supply()
        state.trade(is_pump=True, r=1.0, uid=0)


def test_noraise_3(
        controller_factory, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, price_oracle, accounts, admin):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    with boa.env.anchor():
        state = BigFuzz()
        state.shift_oracle(dp=0.00040075302124023446)
        state.deposit(n=45, ratio=0.7373046875, uid=0, y=18945)


def test_repay_error_1(
        controller_factory, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, price_oracle, accounts, admin):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    with boa.env.anchor():
        state = BigFuzz()
        state.deposit(n=5, ratio=0.5, uid=0, y=505)
        state.trade(is_pump=True, r=1.0, uid=0)
        state.repay(ratio=0.5, uid=0)


def test_not_enough_collateral(
        controller_factory, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, price_oracle, accounts, admin):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    with boa.env.anchor():
        state = BigFuzz()
        state.borrow_more(ratio=0.0, uid=0, y=13840970168756334397)
        state.trade(is_pump=False, r=2.220446049250313e-16, uid=0)
        state.borrow_more(ratio=0.0, uid=7, y=173)
        state.deposit(n=6, ratio=6.103515625e-05, uid=6, y=3526)
        state.trade(is_pump=True, r=1.0, uid=0)
        state.trade(is_pump=False, r=1.0, uid=0)
        state.borrow_more(ratio=0.5, uid=6, y=0)


def test_noraise_4(
        controller_factory, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, price_oracle, accounts, admin):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    with boa.env.anchor():
        state = BigFuzz()
        state.deposit(n=5, ratio=0.5, uid=0, y=505)
        state.trade(is_pump=True, r=1.0, uid=0)
        state.repay(ratio=1.0, uid=0)


def test_debt_nonequal(
        controller_factory, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, price_oracle, accounts, admin):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    with boa.env.anchor():
        state = BigFuzz()
        state.rule_change_rate(rate=183)
        state.deposit(n=5, ratio=0.5, uid=0, y=40072859744991)
        state.time_travel(dt=1)
        state.debt_supply()


def test_noraise_5(
        controller_factory, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, price_oracle, accounts, admin):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    with boa.env.anchor():
        state = BigFuzz()
        state.debt_supply()
        state.self_liquidate_and_health()
        state.debt_supply()
        state.self_liquidate_and_health()
        state.debt_supply()
        state.deposit(n=9, ratio=0.5, uid=1, y=5131452002964343839)
        state.debt_supply()
        state.borrow_more(ratio=0.8847036853778303, uid=1, y=171681017142554251259)


def test_add_collateral_fail(
        controller_factory, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, price_oracle, accounts, admin):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    with boa.env.anchor():
        state = BigFuzz()
        state.debt_supply()
        state.rule_change_rate(rate=5430516289)
        state.debt_supply()
        state.time_travel(dt=1)
        state.debt_supply()
        state.time_travel(dt=1)
        state.debt_supply()
        state.deposit(n=21, ratio=0.8125, uid=3, y=2444)
        state.debt_supply()
        state.time_travel(dt=1860044)
        state.debt_supply()
        state.rule_change_rate(rate=0)
        state.debt_supply()
        state.rule_change_rate(rate=0)
        state.debt_supply()
        state.add_collateral(uid=3, y=1)


def test_debt_eq_repay_no_coins(
        controller_factory, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, price_oracle, accounts, admin):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    with boa.env.anchor():
        state = BigFuzz()
        state.debt_supply()
        state.trade(is_pump=False, r=0.0, uid=0)
        state.debt_supply()
        state.repay(ratio=0.0, uid=0)
        state.debt_supply()
        state.deposit(n=5, ratio=0.5, uid=0, y=505)
        state.debt_supply()
        state.deposit(n=5, ratio=0.5009765625, uid=1, y=519)
        state.debt_supply()
        state.trade(is_pump=True, r=1.0, uid=0)
        state.debt_supply()
        state.repay(ratio=1.0, uid=1)


def test_amount_not_too_low(
        controller_factory, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, price_oracle, accounts, admin):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    with boa.env.anchor():
        state = BigFuzz()
        state.debt_supply()
        state.deposit(n=5, ratio=0.0004882816574536263, uid=0, y=505)
        state.debt_supply()
        state.remove_collateral(uid=0, y=3)


def test_debt_too_high(
        controller_factory, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, price_oracle, accounts, admin):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    with boa.env.anchor():
        state = BigFuzz()
        state.debt_supply()
        state.deposit(n=24, ratio=0.8201103210449219, uid=0, y=18138)
        state.debt_supply()
        state.remove_collateral(uid=0, y=187)


def test_debt_too_high_2(
        controller_factory, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, price_oracle, accounts, admin):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    with boa.env.anchor():
        state = BigFuzz()
        state.shift_oracle(dp=-0.00877380371093752)
        state.shift_oracle(dp=-0.00390625)
        state.deposit(n=29, ratio=0.796142578125, uid=0, y=15877)
