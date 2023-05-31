import boa
import pytest
from math import log2, ceil
from boa.vyper.contract import BoaError
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, run_state_machine_as_test, rule, invariant


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
USE_CALLBACKS = 2


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

    debt_ceiling_change = st.integers(min_value=-10**6 * 10**18, max_value=10**6 * 10**18)

    extended_mode = st.integers(min_value=0, max_value=2)
    liquidate_frac = st.integers(min_value=0, max_value=10**18 + 1)

    use_eth = st.booleans()

    def __init__(self):
        super().__init__()
        self.A = self.market_amm.A()
        self.debt_ceiling = self.controller_factory.debt_ceiling(self.market_controller.address)
        self.fees = 0

    # Auxiliary methods #
    def collect_fees(self):
        fees = self.stablecoin.balanceOf(self.accounts[0])
        try:
            self.market_controller.collect_fees()
        except BoaError:
            with boa.env.prank(self.admin):
                self.controller_factory.collect_fees_above_ceiling(self.market_controller.address)
            self.debt_ceiling = self.controller_factory.debt_ceiling(self.market_controller.address)
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

    def get_max_good_band(self):
        return ceil(log2(self.market_amm.get_base_price() / self.market_amm.price_oracle()) / log2(self.A / (self.A - 1)) + 5)

    def mint_eth(self, amount, use_eth):
        boa.env.set_balance(boa.env.eoa, boa.env.get_balance(boa.env.eoa) + amount)
        if use_eth:
            return {'value': amount}
        else:
            self.weth.deposit(value=amount)
            return {}

    # Borrowing and returning #
    @rule(y=collateral_amount, n=n, uid=user_id, ratio=ratio, use_eth=use_eth)
    def deposit(self, y, n, ratio, uid, use_eth):
        user = self.accounts[uid]
        debt = int(ratio * 3000 * y)
        with boa.env.prank(user):
            kw = self.mint_eth(y, use_eth)
            max_debt = self.market_controller.max_borrowable(y, n)
            if not self.check_debt_ceiling(debt):
                with boa.reverts():
                    self.market_controller.create_loan(y, debt, n, **kw)
                return
            if (debt > max_debt or y // n <= 100 or debt == 0
                    or self.market_controller.loan_exists(user)):
                if debt < max_debt / (0.9999 - 20/(y + 40)):
                    try:
                        self.market_controller.create_loan(y, debt, n, **kw)
                    except Exception:
                        pass
                else:
                    try:
                        self.market_controller.create_loan(y, debt, n, **kw)
                    except Exception:
                        return
                    assert debt < max_debt * (self.A / (self.A - 1))**0.4
                return
            else:
                try:
                    self.market_controller.create_loan(y, debt, n, **kw)
                except BoaError:
                    # Reverts at low numbers due to numerical issues of log calculation
                    # Not a problem because these numbers are not practical to use
                    # And it doesn't allow to create a "bad" loan
                    p_o = self.market_amm.price_oracle()
                    p = self.market_amm.get_p()
                    # Another reason - price increase being too large to handle without oracle following it
                    assert y * ratio < n * 500 or p > p_o
                    return
            self.stablecoin.transfer(self.accounts[0], debt)

    @rule(ratio=ratio, uid=user_id, use_eth=use_eth)
    def repay(self, ratio, uid, use_eth):
        user = self.accounts[uid]
        debt = self.market_controller.debt(user)
        amount = int(ratio * debt)
        self.get_stablecoins(user)
        with boa.env.prank(user):
            if debt == 0 and amount > 0:
                with boa.reverts(fail="insufficient funds"):
                    self.market_controller.repay(amount, user, 2**255-1, use_eth)
            else:
                if amount > 0 and (
                        (amount >= debt and (debt > self.stablecoin.balanceOf(user) + self.market_amm.get_sum_xy(user)[0]))
                        or (amount < debt and (amount > self.stablecoin.balanceOf(user)))):
                    with boa.reverts(fail="insufficient funds"):
                        self.market_controller.repay(amount, user, 2**255-1, use_eth)
                else:
                    self.market_controller.repay(amount, user, 2**255-1, use_eth)
        self.remove_stablecoins(user)

    @rule(y=collateral_amount, uid=user_id, use_eth=use_eth)
    def add_collateral(self, y, uid, use_eth):
        user = self.accounts[uid]
        exists = self.market_controller.loan_exists(user)
        if exists:
            n1, n2 = self.market_amm.read_user_tick_numbers(user)
            n0 = self.market_amm.active_band()

        with boa.env.prank(user):
            kw = self.mint_eth(y, use_eth)
            if (exists and n1 > n0 and self.market_amm.p_oracle_up(n1) < self.market_amm.price_oracle()) or y == 0:
                self.market_controller.add_collateral(y, user, **kw)
            else:
                with boa.reverts():
                    self.market_controller.add_collateral(y, user, **kw)

    @rule(y=collateral_amount, uid=user_id, use_eth=use_eth)
    def remove_collateral(self, y, uid, use_eth):
        user = self.accounts[uid]
        user_collateral, user_stablecoin, debt, N = self.market_controller.user_state(user)
        if debt > 0:
            n1, n2 = self.market_amm.read_user_tick_numbers(user)
            n0 = self.market_amm.active_band()

        with boa.env.prank(user):
            if (debt > 0 and n1 > n0) or y == 0:
                if use_eth:
                    before = boa.env.get_balance(user)
                else:
                    before = self.weth.balanceOf(user)
                min_collateral = self.market_controller.min_collateral(debt, N)
                try:
                    self.market_controller.remove_collateral(y, use_eth)
                except Exception:
                    if user_stablecoin > 0:
                        return
                    if (user_collateral - y) // N <= 100:
                        return
                    if user_collateral - y > min_collateral:
                        raise
                    else:
                        return
                if use_eth:
                    after = boa.env.get_balance(user)
                else:
                    after = self.weth.balanceOf(user)
                assert after - before == y
            else:
                with boa.reverts():
                    self.market_controller.remove_collateral(y, use_eth)

    @rule(y=collateral_amount, uid=user_id, ratio=ratio, use_eth=use_eth)
    def borrow_more(self, y, ratio, uid, use_eth):
        user = self.accounts[uid]

        with boa.env.prank(user):
            kw = self.mint_eth(y, use_eth)

            if not self.market_controller.loan_exists(user):
                with boa.reverts():
                    self.market_controller.borrow_more(y, 1, **kw)

            else:
                sx, sy = self.market_amm.get_sum_xy(user)
                n1, n2 = self.market_amm.read_user_tick_numbers(user)
                n = n2 - n1 + 1
                amount = int(self.market_amm.price_oracle() * (sy + y) / 1e18 * ratio)
                final_debt = self.market_controller.debt(user) + amount

                if not self.check_debt_ceiling(amount) and amount > 0:
                    with boa.reverts():
                        self.market_controller.borrow_more(y, amount, **kw)
                    return

                if sx == 0 or amount == 0:
                    max_debt = self.market_controller.max_borrowable(sy + y, n)
                    if final_debt > max_debt and amount > 0:
                        if final_debt < max_debt / (0.9999 - 20/(y + 40) - 1e-9):
                            try:
                                self.market_controller.borrow_more(y, amount, **kw)
                            except Exception:
                                pass
                        else:
                            with boa.reverts():
                                self.market_controller.borrow_more(y, amount, **kw)
                    else:
                        try:
                            self.market_controller.borrow_more(y, amount, **kw)
                        except Exception:
                            if self.get_max_good_band() > self.market_amm.active_band_with_skip():
                                # Otherwise (if price desync is too large) - this fail is to be expected
                                raise

                else:
                    with boa.reverts():
                        self.market_controller.borrow_more(y, amount, **kw)

    # Trading
    def trade_to_price(self, p):
        user = self.accounts[0]
        with boa.env.prank(user):
            self.collect_fees()
            amount, is_pump = self.market_amm.get_amount_for_price(p)
            if amount > 0:
                if is_pump:
                    self.market_amm.exchange(0, 1, amount, 0)
                    amount_out = self.weth.balanceOf(user)
                    if amount_out > 0:
                        self.weth.withdraw(amount_out)
                else:
                    boa.env.set_balance(user, amount)
                    self.weth.deposit(value=amount)
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
                    amount_out = self.weth.balanceOf(user)
                    if amount_out > 0:
                        self.weth.withdraw(amount_out)
                else:
                    try:
                        self.market_amm.exchange(0, 1, amount, 0)
                    except BoaError:
                        # We may have not enough coins, but no exception if
                        # we are maxed out with the swap size
                        pass
            else:
                amount = int(r * self.weth.balanceOf(self.market_amm.address))
                boa.env.set_balance(user, amount)
                self.weth.deposit(value=amount)
                self.market_amm.exchange(1, 0, amount, 0)
        self.remove_stablecoins(user)

    # Liquidations
    @rule(emode=extended_mode, frac=liquidate_frac, use_eth=use_eth)
    def self_liquidate_and_health(self, emode, frac, use_eth):
        for user in self.accounts:
            try:
                health = self.market_controller.health(user)
            except BoaError:
                # Too deep
                return
            if self.market_controller.loan_exists(user) and health <= 0:
                self.get_stablecoins(user)
                with boa.env.prank(user):
                    if emode == USE_FRACTION:
                        try:
                            self.market_controller.liquidate_extended(
                                    user, 0, frac, use_eth, ZERO_ADDRESS, [])
                        except Exception:
                            if self.market_controller.debt(user) * frac // 10**18 == 0:
                                return
                            raise
                    elif emode == USE_CALLBACKS:
                        self.stablecoin.transfer(self.fake_leverage.address, self.stablecoin.balanceOf(user))
                        try:
                            self.market_controller.liquidate_extended(
                                    user, 0, frac, use_eth,
                                    self.fake_leverage.address, [])
                        except Exception:
                            if self.market_controller.debt(user) * frac // 10**18 == 0:
                                return
                            raise
                    else:
                        self.market_controller.liquidate(user, 0, use_eth)
                self.remove_stablecoins(user)
                if emode == 0 or frac == 10**18:
                    assert not self.market_controller.loan_exists(user)
                    with boa.reverts():
                        self.market_controller.health(user)

    @rule(uid=user_id, luid=liquidator_id, emode=extended_mode, frac=liquidate_frac, use_eth=use_eth)
    def liquidate(self, uid, luid, emode, frac, use_eth):
        user = self.accounts[uid]
        liquidator = self.accounts[luid]
        if user == liquidator:
            return  # self-liquidate tested separately

        with boa.env.prank(liquidator):
            self.fake_leverage.approve_all()

        self.get_stablecoins(liquidator)
        if not self.market_controller.loan_exists(user):
            with boa.env.prank(liquidator):
                with boa.reverts():
                    if emode == USE_FRACTION:
                        self.market_controller.liquidate_extended(
                                user, 0, frac, use_eth, ZERO_ADDRESS, [])
                    elif emode == USE_CALLBACKS:
                        self.stablecoin.transfer(self.fake_leverage.address, self.stablecoin.balanceOf(user))
                        self.market_controller.liquidate_extended(
                                user, 0, frac, use_eth,
                                self.fake_leverage.address, [])
                    else:
                        self.market_controller.liquidate(user, 0, use_eth)
                    if emode == USE_CALLBACKS:
                        self.stablecoin.transferFrom(self.fake_leverage.address, liquidator,
                                                     self.stablecoin.balanceOf(self.fake_leverage.address))
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
                                    user, 0, frac, use_eth, ZERO_ADDRESS, [])
                        elif emode == USE_CALLBACKS:
                            self.stablecoin.transfer(self.fake_leverage.address, self.stablecoin.balanceOf(user))
                            self.market_controller.liquidate_extended(
                                    user, 0, frac, use_eth,
                                    self.fake_leverage.address, [])
                        else:
                            self.market_controller.liquidate(user, 0, use_eth)
                    if emode == USE_CALLBACKS:
                        self.stablecoin.transferFrom(self.fake_leverage.address, liquidator,
                                                     self.stablecoin.balanceOf(self.fake_leverage.address))
                else:
                    if emode == USE_FRACTION:
                        try:
                            self.market_controller.liquidate_extended(
                                    user, 0, frac, use_eth, ZERO_ADDRESS, [])
                        except Exception:
                            if self.market_controller.debt(user) * frac // 10**18 == 0:
                                return
                            raise
                    elif emode == USE_CALLBACKS:
                        self.stablecoin.transfer(self.fake_leverage.address, self.stablecoin.balanceOf(user))
                        try:
                            self.market_controller.liquidate_extended(
                                    user, 0, frac, use_eth,
                                    self.fake_leverage.address, [])
                        except Exception:
                            if self.market_controller.debt(user) * frac // 10**18 == 0:
                                return
                            raise
                    else:
                        self.market_controller.liquidate(user, 0, use_eth)
                    if emode == 0 or frac == 10**18:
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
        if total_debt == 0:
            assert self.market_controller.minted() == self.market_controller.redeemed()
        assert total_debt == self.stablecoin.totalSupply() - self.stablecoin.balanceOf(self.market_controller.address)
        assert abs(sum(self.market_controller.debt(u) for u in self.accounts) - total_debt) <= 10
        # 10 accounts = 10 wei error?

    @invariant()
    def minted_redeemed(self):
        assert self.market_controller.redeemed() + self.market_controller.total_debt() >= self.market_controller.minted()

    # Debt ceiling
    @rule(d_ceil=debt_ceiling_change)
    def change_debt_ceiling(self, d_ceil):
        current_ceil = self.controller_factory.debt_ceiling(self.market_controller.address)
        new_ceil = max(current_ceil + d_ceil, 0)
        with boa.env.prank(self.admin):
            self.controller_factory.set_debt_ceiling(self.market_controller.address, new_ceil)
        self.debt_ceiling = new_ceil

    @rule()
    def rug_debt_ceiling(self):
        with boa.env.prank(self.admin):
            self.controller_factory.rug_debt_ceiling(self.market_controller.address)
        total_debt = self.market_controller.total_debt()
        minted = self.market_controller.minted()
        redeemed = self.market_controller.redeemed()
        if total_debt == 0 and redeemed + total_debt == minted:
            # Debt is 0 and admin fees are claimed
            ceiling = self.controller_factory.debt_ceiling(self.market_controller.address)
            assert self.stablecoin.balanceOf(self.market_controller.address) == ceiling


@pytest.mark.parametrize("_tmp", range(8))  # This splits the test into 8 small chunks which are easier to parallelize
def test_big_fuzz(
        controller_factory, market_amm, market_controller, monetary_policy, weth, stablecoin, price_oracle, accounts,
        fake_leverage, admin, _tmp):
    BigFuzz.TestCase.settings = settings(max_examples=313, stateful_step_count=20)
    # Or quick check
    # BigFuzz.TestCase.settings = settings(max_examples=25, stateful_step_count=20)
    collateral_token = weth
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    run_state_machine_as_test(BigFuzz)


def test_liquidate_no_coins(
        controller_factory, market_amm, market_controller, monetary_policy, weth, stablecoin, price_oracle, accounts, fake_leverage, admin):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    state = BigFuzz()
    state.debt_supply()
    state.minted_redeemed()
    state.rug_debt_ceiling()
    state.debt_supply()
    state.minted_redeemed()
    state.rug_debt_ceiling()
    state.debt_supply()
    state.minted_redeemed()
    state.rug_debt_ceiling()
    state.debt_supply()
    state.minted_redeemed()
    state.rug_debt_ceiling()
    state.debt_supply()
    state.minted_redeemed()
    state.rug_debt_ceiling()
    state.debt_supply()
    state.minted_redeemed()
    state.rule_change_rate(rate=0)
    state.debt_supply()
    state.minted_redeemed()
    state.rug_debt_ceiling()
    state.debt_supply()
    state.minted_redeemed()
    state.add_collateral(uid=0, use_eth=False, y=0)
    state.debt_supply()
    state.minted_redeemed()
    state.rug_debt_ceiling()
    state.debt_supply()
    state.minted_redeemed()
    state.deposit(n=5, ratio=0.5, uid=1, use_eth=False, y=14458)
    state.debt_supply()
    state.minted_redeemed()
    state.borrow_more(ratio=0.25, uid=1, use_eth=False, y=14457)
    state.debt_supply()
    state.minted_redeemed()
    state.rug_debt_ceiling()
    state.debt_supply()
    state.minted_redeemed()
    state.liquidate(emode=2, frac=0, luid=0, uid=1, use_eth=False)
    state.teardown()
