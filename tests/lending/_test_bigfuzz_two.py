import boa
from math import log2, ceil
from boa import BoaError
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, run_state_machine_as_test, rule  # , invariant


# Variables and methods to check
# * A

# * liquidate
# * self_liquidate
# * set_amm_fee
# * set_amm_admin_fee
# * set_debt_ceiling
# * set_borrowing_discounts
# * collect AMM fees

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
USE_FRACTION = 1
MIN_RATE = 10**15 / (365 * 86400)  # 0.1%
MAX_RATE = 10**19 / (365 * 86400)  # 1000%


class BigFuzz(RuleBasedStateMachine):
    collateral_amount = st.integers(min_value=0, max_value=10**18 * 10**6 // 3000)
    loan_amount = st.integers(min_value=0, max_value=10**18 * 10**6)
    n = st.integers(min_value=5, max_value=50)
    ratio = st.floats(min_value=0, max_value=2)

    is_pump = st.booleans()
    rate = st.integers(min_value=0, max_value=int(1e18 * 0.2 / 365 / 86400))
    oracle_step = st.floats(min_value=-0.01, max_value=0.01)

    user_id = st.integers(min_value=0, max_value=9)
    liquidator_id = st.integers(min_value=0, max_value=9)
    time_shift = st.integers(min_value=1, max_value=30 * 86400)

    extended_mode = st.integers(min_value=0, max_value=1)
    is_short = st.booleans()
    liquidate_frac = st.integers(min_value=0, max_value=10**18 + 1)

    def __init__(self):
        super().__init__()

        self.mpolicy_long = self.mpolicy_interface.at(self.controller_long.monetary_policy())
        self.mpolicy_short = self.mpolicy_interface.at(self.controller_short.monetary_policy())

        self.A = self.amm_long.A()
        assert self.A == self.amm_short.A()

        self.collateral_mul = 10**(18 - self.collateral_token.decimals())
        self.borrowed_mul = 10**(18 - self.borrowed_token.decimals())
        self.mul = {}
        self.mul[False] = self.borrowed_mul
        self.mul[True] = self.collateral_mul
        self.tokens_b = {}
        self.tokens_b[False] = self.borrowed_token
        self.tokens_b[True] = self.collateral_token
        self.vaults_c = {}
        self.vaults_c[False] = self.vault_short
        self.vaults_c[True] = self.vault_long
        self.vaults = {}
        self.vaults[False] = self.vault_long
        self.vaults[True] = self.vault_short
        self.controllers = {}
        self.controllers[False] = self.controller_long
        self.controllers[True] = self.controller_short
        self.amms = {}
        self.amms[False] = self.amm_short
        self.amms[True] = self.amm_long

        for user in self.accounts:
            with boa.env.prank(user):
                self.borrowed_token.approve(self.vault_long.address, 2**256-1)
                self.collateral_token.approve(self.vault_short.address, 2**256-1)

                self.borrowed_token.approve(self.amm_long.address, 2**256-1)
                self.borrowed_token.approve(self.controller_long.address, 2**256-1)
                self.vault_short.approve(self.amm_long.address, 2**256-1)
                self.vault_short.approve(self.controller_long.address, 2**256-1)

                self.collateral_token.approve(self.amm_short.address, 2**256-1)
                self.collateral_token.approve(self.controller_short.address, 2**256-1)
                self.vault_long.approve(self.amm_short.address, 2**256-1)
                self.vault_long.approve(self.controller_short.address, 2**256-1)

    # Auxiliary methods #
    def check_debt_ceiling(self, amount, is_short):
        return self.tokens_b.balanceOf(self.controllers[is_short].address) >= amount

    def get_max_good_band(self, is_short):
        return ceil(log2(self.amms[is_short].get_base_price() / self.amms[is_short].price_oracle()) / log2(self.A / (self.A - 1)) + 5)

    @rule(uid=user_id, asset_amount=loan_amount, is_short=is_short)
    def deposit_vault(self, uid, asset_amount, is_short):
        asset_amount = asset_amount // self.mul[is_short]
        user = self.accounts[uid]
        balance = self.tokens_b[is_short].balanceOf(user)
        if balance < asset_amount:
            self.tokens_b[is_short]._mint_for_testing(user, asset_amount - balance)
        with boa.env.prank(user):
            self.vaults[is_short].deposit(asset_amount)

    @rule(uid=user_id, shares_amount=loan_amount, is_short=is_short)
    def withdraw_vault(self, uid, shares_amount, is_short):
        user = self.accounts[uid]
        if shares_amount <= self.vaults[is_short].maxRedeem(user):
            with boa.env.prank(user):
                self.vaults[is_short].redeem(shares_amount)

    # Borrowing and returning #
    # @rule(y=collateral_amount, n=n, uid=user_id, ratio=ratio, is_short=is_short)
    def create_loan(self, y, n, ratio, uid, is_short):
        debt = int(ratio * 3000 * y) // self.borrowed_mul
        y = y // self.collateral_mul
        user = self.accounts[uid]
        with boa.env.prank(user):
            self.collateral_token._mint_for_testing(user, y)
            max_debt = self.market_controller.max_borrowable(y, n)
            if not self.check_debt_ceiling(debt):
                with boa.reverts():
                    self.market_controller.create_loan(y, debt, n)
                return
            if (debt > max_debt or y * self.collateral_mul // n <= 100 or debt == 0
                    or self.market_controller.loan_exists(user)):
                if debt < max_debt / (0.9999 - 20/(y * self.collateral_mul + 40)):
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
                try:
                    self.market_controller.create_loan(y, debt, n)
                except BoaError:
                    # Reverts at low numbers due to numerical issues of log calculation
                    # Not a problem because these numbers are not practical to use
                    # And it doesn't allow to create a "bad" loan
                    p_o = self.market_amm.price_oracle()
                    p = self.market_amm.get_p()
                    # Another reason - price increase being too large to handle without oracle following it
                    # XXX check of self.borrowed_mul is here also
                    assert y * ratio * self.collateral_mul < n * 500 or p > p_o
                    return

    # @rule(ratio=ratio, uid=user_id)
    def repay(self, ratio, uid):
        user = self.accounts[uid]
        debt = self.market_controller.debt(user)
        amount = int(ratio * debt)
        diff = amount - self.borrowed_token.balanceOf(user)
        if diff > 0:
            with boa.env.prank(user):
                self.borrowed_token._mint_for_testing(user, diff)
        with boa.env.prank(user):
            if debt == 0 and amount > 0:
                with boa.reverts():
                    self.market_controller.repay(amount, user)
            else:
                if amount > 0 and (
                        (amount >= debt and (debt > self.borrowed_token.balanceOf(user) + self.market_amm.get_sum_xy(user)[0]))
                        or (amount < debt and (amount > self.borrowed_token.balanceOf(user)))):
                    with boa.reverts():
                        self.market_controller.repay(amount, user)
                else:
                    self.market_controller.repay(amount, user)

    # @rule(y=collateral_amount, uid=user_id)
    def add_collateral(self, y, uid):
        y = y // self.collateral_mul
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

    # @rule(y=collateral_amount, uid=user_id)
    def remove_collateral(self, y, uid):
        y = y // self.collateral_mul
        user = self.accounts[uid]
        user_collateral, user_borrowed, debt, N = self.market_controller.user_state(user)
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
                    if user_borrowed > 0:
                        return
                    if (user_collateral - y) * self.collateral_mul // N <= 100:
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

    # @rule(y=collateral_amount, uid=user_id, ratio=ratio)
    def borrow_more(self, y, ratio, uid):
        y = y // self.collateral_mul
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
                amount = int(self.market_amm.price_oracle() * (sy + y) * self.collateral_mul / 1e18 * ratio / self.borrowed_mul)
                current_debt = self.market_controller.debt(user)
                final_debt = current_debt + amount

                if not self.check_debt_ceiling(amount) and amount > 0:
                    with boa.reverts():
                        self.market_controller.borrow_more(y, amount)
                    return

                if sx == 0 or amount == 0:
                    max_debt = self.market_controller.max_borrowable(sy + y, n, current_debt)
                    if final_debt > max_debt and amount > 0:
                        # XXX any borrowed_mul here?
                        if final_debt < max_debt / (0.9999 - 20/(y * self.collateral_mul + 40) - 1e-9):
                            try:
                                self.market_controller.borrow_more(y, amount)
                            except Exception:
                                pass
                        else:
                            with boa.reverts():
                                self.market_controller.borrow_more(y, amount)
                    else:
                        try:
                            self.market_controller.borrow_more(y, amount)
                        except Exception:
                            if self.get_max_good_band() > self.market_amm.active_band_with_skip():
                                # Otherwise (if price desync is too large) - this fail is to be expected
                                raise

                else:
                    with boa.reverts():
                        self.market_controller.borrow_more(y, amount)

    # Trading
    def trade_to_price(self, p):
        user = self.accounts[0]
        with boa.env.prank(user):
            amount, is_pump = self.market_amm.get_amount_for_price(p)
            if amount > 0:
                if is_pump:
                    self.borrowed_token._mint_for_testing(user, amount)
                    self.market_amm.exchange(0, 1, amount, 0)
                else:
                    self.collateral_token._mint_for_testing(user, amount)
                    self.market_amm.exchange(1, 0, amount, 0)

    # @rule(r=ratio, is_pump=is_pump, uid=user_id)
    def trade(self, r, is_pump, uid):
        user = self.accounts[uid]
        with boa.env.prank(user):
            if is_pump:
                amount = int(r * self.borrowed_token.totalSupply())
                self.borrowed_token._mint_for_testing(user, amount)
                self.market_amm.exchange(0, 1, amount, 0)
            else:
                amount = int(r * self.collateral_token.totalSupply())
                self.collateral_token._mint_for_testing(user, amount)
                self.market_amm.exchange(1, 0, amount, 0)

    # @rule(emode=extended_mode, frac=liquidate_frac)
    def self_liquidate_and_health(self, emode, frac):
        for user in self.accounts:
            try:
                health = self.market_controller.health(user)
            except BoaError:
                # Too deep
                return
            if self.market_controller.loan_exists(user) and health <= 0:
                with boa.env.prank(user):
                    debt = self.market_controller.debt(user)
                    diff = debt - self.borrowed_token.balanceOf(user)
                    if diff > 0:
                        self.borrowed_token._mint_for_testing(user, diff)
                    if emode == USE_FRACTION:
                        try:
                            self.market_controller.liquidate_extended(
                                    user, 0, frac, True, ZERO_ADDRESS, [])
                        except Exception:
                            if self.market_controller.debt(user) * frac // 10**18 == 0:
                                return
                            raise
                    else:
                        self.market_controller.liquidate(user, 0)
                if emode == 0 or frac == 10**18:
                    assert not self.market_controller.loan_exists(user)
                    with boa.reverts():
                        self.market_controller.health(user)

    # @rule(uid=user_id, luid=liquidator_id, emode=extended_mode, frac=liquidate_frac)
    def liquidate(self, uid, luid, emode, frac):
        user = self.accounts[uid]
        liquidator = self.accounts[luid]
        if user == liquidator:
            return  # self-liquidate tested separately

        with boa.env.prank(liquidator):
            self.fake_leverage.approve_all()

        if not self.market_controller.loan_exists(user):
            debt = self.market_controller.debt(user)
            diff = debt - self.borrowed_token.balanceOf(user)
            if diff > 0:
                self.borrowed_token._mint_for_testing(liquidator, diff)

            with boa.env.prank(liquidator):
                with boa.reverts():
                    if emode == USE_FRACTION:
                        self.market_controller.liquidate_extended(
                                user, 0, frac, True, ZERO_ADDRESS, [])
                    else:
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
                        if emode == USE_FRACTION:
                            self.market_controller.liquidate_extended(
                                    user, 0, frac, True, ZERO_ADDRESS, [])
                        else:
                            self.market_controller.liquidate(user, 0)
                else:
                    if emode == USE_FRACTION:
                        try:
                            self.market_controller.liquidate_extended(
                                    user, 0, frac, True, ZERO_ADDRESS, [])
                        except Exception:
                            if self.market_controller.debt(user) * frac // 10**18 == 0:
                                return
                            raise
                    else:
                        self.market_controller.liquidate(user, 0)
                    if emode == 0 or frac == 10**18:
                        with boa.reverts():
                            self.market_controller.health(user)

    # Other
    # @rule(dp=oracle_step)
    def shift_oracle(self, dp):
        # Oracle shift is done via adiabatic trading which shouldn't decrease health
        if dp != 0:
            p0 = self.price_oracle.price()
            self.trade_to_price(p0)
            p = int(p0 * (1 + dp))
            with boa.env.prank(self.admin):
                self.price_oracle.set_price(p)
            self.trade_to_price(p)

    # @rule(min_rate=rate, max_rate=rate)
    def rule_change_rate(self, min_rate, max_rate):
        with boa.env.prank(self.admin):
            if min_rate > max_rate or min(min_rate, max_rate) < MIN_RATE or max(min_rate, max_rate) > MAX_RATE:
                with boa.reverts():
                    self.market_mpolicy.set_rates(min_rate, max_rate)
            else:
                self.market_mpolicy.set_rates(min_rate, max_rate)

    # @rule(dt=time_shift)
    def time_travel(self, dt):
        boa.env.time_travel(dt)

    # @invariant()
    def debt_supply(self):
        total_debt = self.market_controller.total_debt()
        if total_debt == 0:
            assert abs(self.market_controller.minted() - self.market_controller.redeemed()) <= 1
        assert abs(sum(self.market_controller.debt(u) for u in self.accounts) - total_debt) <= 10

    # @invariant()
    def minted_redeemed(self):
        assert self.market_controller.redeemed() + self.market_controller.total_debt() >= self.market_controller.minted()


def test_big_fuzz(
        vault_long, vault_short, borrowed_token, collateral_token,
        amm_long, amm_short, controller_long, controller_short,
        price_oracle, mpolicy_interface):
    BigFuzz.TestCase.settings = settings(max_examples=200, stateful_step_count=20)
    # Or quick check
    # BigFuzz.TestCase.settings = settings(max_examples=25, stateful_step_count=20)
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    run_state_machine_as_test(BigFuzz)
