import boa
import pytest
from math import log2, ceil
from boa import BoaError
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    run_state_machine_as_test,
    rule,
    invariant,
)

from tests.utils.deployers import AMM_DEPLOYER, MINT_CONTROLLER_DEPLOYER

# Variables and methods to check
# * A

# * liquidate
# * self_liquidate
# * set_amm_fee
# * set_debt_ceiling
# * set_borrowing_discounts
# * collect AMM fees
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

    debt_ceiling_change = st.integers(
        min_value=-(10**6) * 10**18, max_value=10**6 * 10**18
    )

    extended_mode = st.integers(min_value=0, max_value=2)
    liquidate_frac = st.integers(min_value=0, max_value=10**18 + 1)

    def __init__(self):
        super().__init__()
        self.A = self.market_amm.A()
        self.debt_ceiling = self.controller_factory.debt_ceiling(
            self.market_controller.address
        )
        self.fees = 0
        self.collateral_mul = 10 ** (18 - self.collateral_token.decimals())

    # Auxiliary methods #
    def collect_fees(self):
        fees = self.stablecoin.balanceOf(self.accounts[0])
        try:
            self.market_controller.collect_fees()
        except BoaError:
            with boa.env.prank(self.admin):
                self.controller_factory.collect_fees_above_ceiling(
                    self.market_controller.address
                )
            self.debt_ceiling = self.controller_factory.debt_ceiling(
                self.market_controller.address
            )
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
        return ceil(
            log2(self.market_amm.get_base_price() / self.market_amm.price_oracle())
            / log2(self.A / (self.A - 1))
            + 5
        )

    # Borrowing and returning #
    @rule(y=collateral_amount, n=n, uid=user_id, ratio=ratio)
    def deposit(self, y, n, ratio, uid):
        debt = int(ratio * 3000 * y)
        y = y // self.collateral_mul
        user = self.accounts[uid]
        with boa.env.prank(user):
            boa.deal(self.collateral_token, user, y)
            max_debt = self.market_controller.max_borrowable(y, n)
            if not self.check_debt_ceiling(debt):
                with boa.reverts():
                    self.market_controller.create_loan(y, debt, n)
                return
            if (
                debt > max_debt
                or y * self.collateral_mul // n <= 100
                or debt == 0
                or self.market_controller.loan_exists(user)
            ):
                if debt < max_debt / (0.9999 - 20 / (y * self.collateral_mul + 40)):
                    try:
                        self.market_controller.create_loan(y, debt, n)
                    except Exception:
                        pass
                else:
                    try:
                        self.market_controller.create_loan(y, debt, n)
                    except Exception:
                        return
                    assert debt < max_debt * (self.A / (self.A - 1)) ** 0.4
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
                    assert y * ratio * self.collateral_mul < n * 500 or p > p_o
                    return
            self.stablecoin.transfer(self.accounts[0], debt)

    @rule(ratio=ratio, uid=user_id)
    def repay(self, ratio, uid):
        user = self.accounts[uid]
        debt = self.market_controller.debt(user)
        amount = int(ratio * debt)
        self.get_stablecoins(user)
        with boa.env.prank(user):
            if debt == 0 and amount > 0:
                with boa.reverts():
                    self.market_controller.repay(amount, user)
            else:
                if amount > 0:
                    if (
                        amount >= debt
                        and (
                            debt
                            > self.stablecoin.balanceOf(user)
                            + self.market_amm.get_sum_xy(user)[0]
                        )
                    ) or (amount < debt and (amount > self.stablecoin.balanceOf(user))):
                        with boa.reverts():
                            self.market_controller.repay(amount, user)
                    else:
                        self.market_controller.repay(amount, user)
        self.remove_stablecoins(user)

    @rule(y=collateral_amount, uid=user_id)
    def add_collateral(self, y, uid):
        y = y // self.collateral_mul
        user = self.accounts[uid]
        exists = self.market_controller.loan_exists(user)
        if exists:
            n1, n2 = self.market_amm.read_user_tick_numbers(user)
            n0 = self.market_amm.active_band()
        boa.deal(self.collateral_token, user, y)

        with boa.env.prank(user):
            if (
                exists
                and n1 > n0
                and self.market_amm.p_oracle_up(n1) < self.market_amm.price_oracle()
            ) or y == 0:
                self.market_controller.add_collateral(y, user)
            else:
                with boa.reverts():
                    self.market_controller.add_collateral(y, user)

    @rule(y=collateral_amount, uid=user_id)
    def remove_collateral(self, y, uid):
        y = y // self.collateral_mul
        user = self.accounts[uid]
        user_collateral, user_stablecoin, debt, N = self.market_controller.user_state(
            user
        )
        if debt > 0:
            n1, n2 = self.market_amm.read_user_tick_numbers(user)
            n0 = self.market_amm.active_band()

        with boa.env.prank(user):
            if (debt > 0 and n1 > n0) or y == 0:
                before = self.collateral_token.balanceOf(user)
                if debt > 0:
                    min_collateral = self.market_controller.min_collateral(debt, N)
                else:
                    return
                try:
                    self.market_controller.remove_collateral(y)
                except Exception:
                    if user_stablecoin > 0:
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

    @rule(y=collateral_amount, uid=user_id, ratio=ratio)
    def borrow_more(self, y, ratio, uid):
        y = y // self.collateral_mul
        user = self.accounts[uid]
        boa.deal(self.collateral_token, user, y)

        with boa.env.prank(user):
            if not self.market_controller.loan_exists(user):
                with boa.reverts():
                    self.market_controller.borrow_more(y, 1)

            else:
                sx, sy = self.market_amm.get_sum_xy(user)
                n1, n2 = self.market_amm.read_user_tick_numbers(user)
                n = n2 - n1 + 1
                amount = int(
                    self.market_amm.price_oracle()
                    * (sy + y)
                    * self.collateral_mul
                    / 1e18
                    * ratio
                )
                current_debt = self.market_controller.debt(user)
                final_debt = current_debt + amount

                if not self.check_debt_ceiling(amount) and amount > 0:
                    with boa.reverts():
                        self.market_controller.borrow_more(y, amount)
                    return

                if sx == 0 or amount == 0:
                    max_debt = current_debt + self.market_controller.max_borrowable(
                        y, n, user
                    )
                    if final_debt > max_debt and amount > 0:
                        if final_debt < max_debt / (
                            0.9999 - 20 / (y * self.collateral_mul + 40) - 1e-9
                        ):
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
                            if (
                                self.get_max_good_band()
                                > self.market_amm.active_band_with_skip()
                            ):
                                # Otherwise (if price desync is too large) - this fail is to be expected
                                raise

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
                    boa.deal(self.collateral_token, user, amount)
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
                boa.deal(self.collateral_token, user, amount)
                self.market_amm.exchange(1, 0, amount, 0)
        self.remove_stablecoins(user)

    # Liquidations
    @rule(emode=extended_mode, frac=liquidate_frac)
    def self_liquidate_and_health(self, emode, frac):
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
                            self.market_controller.liquidate(user, 0, frac)
                        except Exception:
                            if self.market_controller.debt(user) * frac // 10**18 == 0:
                                return
                            raise
                    elif emode == USE_CALLBACKS:
                        self.stablecoin.transfer(
                            self.fake_leverage.address, self.stablecoin.balanceOf(user)
                        )
                        try:
                            self.market_controller.liquidate(
                                user, 0, frac, self.fake_leverage.address, b""
                            )
                        except Exception:
                            if self.market_controller.debt(user) * frac // 10**18 == 0:
                                return
                            raise
                    else:
                        self.market_controller.liquidate(user, 0)
                self.remove_stablecoins(user)
                if emode == 0 or frac == 10**18:
                    assert not self.market_controller.loan_exists(user)
                    with boa.reverts():
                        self.market_controller.health(user)

    @rule(uid=user_id, luid=liquidator_id, emode=extended_mode, frac=liquidate_frac)
    def liquidate(self, uid, luid, emode, frac):
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
                        self.market_controller.liquidate(user, 0, frac)
                    elif emode == USE_CALLBACKS:
                        self.stablecoin.transfer(
                            self.fake_leverage.address, self.stablecoin.balanceOf(user)
                        )
                        self.market_controller.liquidate(
                            user, 0, frac, self.fake_leverage.address, b""
                        )
                    else:
                        self.market_controller.liquidate(user, 0)
                    if emode == USE_CALLBACKS:
                        self.stablecoin.transferFrom(
                            self.fake_leverage.address,
                            liquidator,
                            self.stablecoin.balanceOf(self.fake_leverage.address),
                        )
        else:
            health_limit = self.market_controller.liquidation_discount()
            try:
                health = self.market_controller.health(user, True)
            except Exception as e:
                assert "Too deep" in str(e)
            with boa.env.prank(liquidator):
                if health >= health_limit:
                    with boa.reverts():
                        if emode == USE_FRACTION:
                            self.market_controller.liquidate(user, 0, frac)
                        elif emode == USE_CALLBACKS:
                            self.stablecoin.transfer(
                                self.fake_leverage.address,
                                self.stablecoin.balanceOf(user),
                            )
                            self.market_controller.liquidate(
                                user, 0, frac, self.fake_leverage.address, b""
                            )
                        else:
                            self.market_controller.liquidate(user, 0)
                    if emode == USE_CALLBACKS:
                        self.stablecoin.transferFrom(
                            self.fake_leverage.address,
                            liquidator,
                            self.stablecoin.balanceOf(self.fake_leverage.address),
                        )
                else:
                    if emode == USE_FRACTION:
                        try:
                            self.market_controller.liquidate(user, 0, frac)
                        except Exception:
                            if self.market_controller.debt(user) * frac // 10**18 == 0:
                                return
                            raise
                    elif emode == USE_CALLBACKS:
                        self.stablecoin.transfer(
                            self.fake_leverage.address, self.stablecoin.balanceOf(user)
                        )
                        try:
                            self.market_controller.liquidate(
                                user, 0, frac, self.fake_leverage.address, b""
                            )
                        except Exception:
                            if self.market_controller.debt(user) * frac // 10**18 == 0:
                                return
                            raise
                    else:
                        self.market_controller.liquidate(user, 0)
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
        assert total_debt == self.controller_factory.debt_ceiling_residual(
            self.market_controller
        ) - self.stablecoin.balanceOf(self.market_controller.address)
        assert (
            abs(sum(self.market_controller.debt(u) for u in self.accounts) - total_debt)
            <= 10
        )
        # 10 accounts = 10 wei error?

    @invariant()
    def minted_redeemed(self):
        assert (
            self.market_controller.redeemed() + self.market_controller.total_debt()
            >= self.market_controller.minted()
        )

    # Debt ceiling
    @rule(d_ceil=debt_ceiling_change)
    def change_debt_ceiling(self, d_ceil):
        current_ceil = self.controller_factory.debt_ceiling(
            self.market_controller.address
        )
        new_ceil = max(current_ceil + d_ceil, 0)
        with boa.env.prank(self.admin):
            self.controller_factory.set_debt_ceiling(
                self.market_controller.address, new_ceil
            )
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
            ceiling = self.controller_factory.debt_ceiling(
                self.market_controller.address
            )
            assert self.stablecoin.balanceOf(self.market_controller.address) == ceiling


@pytest.mark.parametrize(
    "_tmp", range(4)
)  # This splits the test into 8 small chunks which are easier to parallelize
@pytest.mark.parametrize("collateral_digits", [8, 18])
def test_big_fuzz(
    controller_factory,
    get_market,
    monetary_policy,
    collateral_digits,
    stablecoin,
    price_oracle,
    accounts,
    get_fake_leverage,
    admin,
    _tmp,
):
    from tests.utils.deployers import ERC20_MOCK_DEPLOYER

    collateral_token = ERC20_MOCK_DEPLOYER.deploy(collateral_digits)
    market = get_market(collateral_token)
    market_amm = AMM_DEPLOYER.at(market.get_amm(collateral_token.address))
    market_controller = MINT_CONTROLLER_DEPLOYER.at(
        market.get_controller(collateral_token.address)
    )
    fake_leverage = get_fake_leverage(collateral_token, market_controller)

    BigFuzz.TestCase.settings = settings(max_examples=50, stateful_step_count=20)
    # Or quick check
    # BigFuzz.TestCase.settings = settings(max_examples=25, stateful_step_count=20)
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    run_state_machine_as_test(BigFuzz)


def test_noraise(
    controller_factory,
    market_amm,
    market_controller,
    monetary_policy,
    collateral_token,
    stablecoin,
    price_oracle,
    accounts,
    fake_leverage,
    admin,
):
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
    controller_factory,
    market_amm,
    market_controller,
    monetary_policy,
    collateral_token,
    stablecoin,
    price_oracle,
    accounts,
    fake_leverage,
    admin,
):
    # This is due to evmdiv working not like floor div (fixed)
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    with boa.env.anchor():
        state = BigFuzz()
        state.shift_oracle(dp=2.3841130314394837e-09)
        state.deposit(n=5, ratio=0.9340958492675753, uid=0, y=4063)


def test_exchange_fails(
    controller_factory,
    market_amm,
    market_controller,
    monetary_policy,
    collateral_token,
    stablecoin,
    price_oracle,
    accounts,
    fake_leverage,
    admin,
):
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
    controller_factory,
    market_amm,
    market_controller,
    monetary_policy,
    collateral_token,
    stablecoin,
    price_oracle,
    accounts,
    fake_leverage,
    admin,
):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    with boa.env.anchor():
        state = BigFuzz()
        state.shift_oracle(dp=0.00040075302124023446)
        state.deposit(n=45, ratio=0.7373046875, uid=0, y=18945)


def test_repay_error_1(
    controller_factory,
    market_amm,
    market_controller,
    monetary_policy,
    collateral_token,
    stablecoin,
    price_oracle,
    accounts,
    fake_leverage,
    admin,
):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    with boa.env.anchor():
        state = BigFuzz()
        state.deposit(n=5, ratio=0.5, uid=0, y=505)
        state.trade(is_pump=True, r=1.0, uid=0)
        state.repay(ratio=0.5, uid=0)


def test_not_enough_collateral(
    controller_factory,
    market_amm,
    market_controller,
    monetary_policy,
    collateral_token,
    stablecoin,
    price_oracle,
    accounts,
    fake_leverage,
    admin,
):
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
    controller_factory,
    market_amm,
    market_controller,
    monetary_policy,
    collateral_token,
    stablecoin,
    price_oracle,
    accounts,
    fake_leverage,
    admin,
):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    with boa.env.anchor():
        state = BigFuzz()
        state.deposit(n=5, ratio=0.5, uid=0, y=505)
        state.trade(is_pump=True, r=1.0, uid=0)
        state.repay(ratio=1.0, uid=0)


def test_debt_nonequal(
    controller_factory,
    market_amm,
    market_controller,
    monetary_policy,
    collateral_token,
    stablecoin,
    price_oracle,
    accounts,
    fake_leverage,
    admin,
):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    with boa.env.anchor():
        state = BigFuzz()
        state.rule_change_rate(rate=183)
        state.deposit(n=5, ratio=0.5, uid=0, y=40072859744991)
        state.time_travel(dt=1)
        state.debt_supply()


def test_noraise_5(
    controller_factory,
    market_amm,
    market_controller,
    monetary_policy,
    collateral_token,
    stablecoin,
    price_oracle,
    accounts,
    fake_leverage,
    admin,
):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    with boa.env.anchor():
        state = BigFuzz()
        state.debt_supply()
        state.self_liquidate_and_health(0, 0)
        state.debt_supply()
        state.self_liquidate_and_health(0, 0)
        state.debt_supply()
        state.deposit(n=9, ratio=0.5, uid=1, y=5131452002964343839)
        state.debt_supply()
        state.borrow_more(ratio=0.8847036853778303, uid=1, y=171681017142554251259)


def test_add_collateral_fail(
    controller_factory,
    market_amm,
    market_controller,
    monetary_policy,
    collateral_token,
    stablecoin,
    price_oracle,
    accounts,
    fake_leverage,
    admin,
):
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
    controller_factory,
    market_amm,
    market_controller,
    monetary_policy,
    collateral_token,
    stablecoin,
    price_oracle,
    accounts,
    fake_leverage,
    admin,
):
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
    controller_factory,
    market_amm,
    market_controller,
    monetary_policy,
    collateral_token,
    stablecoin,
    price_oracle,
    accounts,
    fake_leverage,
    admin,
):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    with boa.env.anchor():
        state = BigFuzz()
        state.debt_supply()
        state.deposit(n=5, ratio=0.0004882816574536263, uid=0, y=505)
        state.debt_supply()
        state.remove_collateral(uid=0, y=3)


def test_debt_too_high(
    controller_factory,
    market_amm,
    market_controller,
    monetary_policy,
    collateral_token,
    stablecoin,
    price_oracle,
    accounts,
    fake_leverage,
    admin,
):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    with boa.env.anchor():
        state = BigFuzz()
        state.debt_supply()
        state.deposit(n=24, ratio=0.8201103210449219, uid=0, y=18138)
        state.debt_supply()
        state.remove_collateral(uid=0, y=187)


def test_debt_too_high_2(
    controller_factory,
    market_amm,
    market_controller,
    monetary_policy,
    collateral_token,
    stablecoin,
    price_oracle,
    accounts,
    fake_leverage,
    admin,
):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    with boa.env.anchor():
        state = BigFuzz()
        state.shift_oracle(dp=-0.00877380371093752)
        state.shift_oracle(dp=-0.00390625)
        state.deposit(n=29, ratio=0.796142578125, uid=0, y=15877)


def test_change_debt_ceiling_error(
    controller_factory,
    market_amm,
    market_controller,
    monetary_policy,
    collateral_token,
    stablecoin,
    price_oracle,
    accounts,
    fake_leverage,
    admin,
):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    state = BigFuzz()
    state.change_debt_ceiling(d_ceil=-999999999999999650753500)
    state.rule_change_rate(rate=2863307149)
    state.deposit(n=5, ratio=0.5, uid=0, y=232831)
    state.time_travel(dt=1)
    state.debt_supply()  # Interest is above the coins we have, so debt ceiling is increased


def test_borrow_zero_norevert(
    controller_factory,
    market_amm,
    market_controller,
    monetary_policy,
    collateral_token,
    stablecoin,
    price_oracle,
    accounts,
    fake_leverage,
    admin,
):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    state = BigFuzz()
    state.deposit(n=5, ratio=0.5, uid=0, y=18879089852719101952)
    state.change_debt_ceiling(d_ceil=-971681365220921345835009)
    # Important that we borrow 0 after changing the debt ceiling
    state.borrow_more(ratio=0.0, uid=0, y=0)


def test_debt_too_high_3(
    controller_factory,
    market_amm,
    market_controller,
    monetary_policy,
    collateral_token,
    stablecoin,
    price_oracle,
    accounts,
    fake_leverage,
    admin,
):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    state = BigFuzz()
    state.rule_change_rate(rate=0)
    state.deposit(n=5, ratio=0.5, uid=0, y=505)
    state.trade(is_pump=True, r=1.0, uid=0)
    state.deposit(n=5, ratio=0.5, uid=1, y=505)


def test_debt_too_high_4(
    controller_factory,
    market_amm,
    market_controller,
    monetary_policy,
    collateral_token,
    stablecoin,
    price_oracle,
    accounts,
    fake_leverage,
    admin,
):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    state = BigFuzz()
    state.deposit(n=5, ratio=0.3684895833333333, uid=0, y=57525)
    state.trade(is_pump=False, r=1.1, uid=0)
    state.trade(is_pump=True, r=1.0, uid=0)
    state.deposit(n=5, ratio=0.5624999999999999, uid=1, y=757895)


def test_loan_doesnt_exist(
    controller_factory,
    market_amm,
    market_controller,
    monetary_policy,
    collateral_token,
    stablecoin,
    price_oracle,
    accounts,
    fake_leverage,
    admin,
):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    state = BigFuzz()
    state.debt_supply()
    state.minted_redeemed()
    state.rug_debt_ceiling()
    state.debt_supply()
    state.minted_redeemed()
    state.change_debt_ceiling(d_ceil=0)
    state.debt_supply()
    state.minted_redeemed()
    state.deposit(n=5, ratio=0.25, uid=1, y=505)
    state.debt_supply()
    state.minted_redeemed()
    state.trade(is_pump=True, r=1.0, uid=0)
    state.debt_supply()
    state.minted_redeemed()
    state.deposit(n=8, ratio=1.52587890625e-05, uid=0, y=1610)
    state.debt_supply()
    state.minted_redeemed()
    state.self_liquidate_and_health(emode=1, frac=0)


def test_debt_too_high_2_users(
    controller_factory,
    market_amm,
    market_controller,
    monetary_policy,
    collateral_token,
    stablecoin,
    price_oracle,
    accounts,
    fake_leverage,
    admin,
):
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    state = BigFuzz()
    state.debt_supply()
    state.minted_redeemed()
    state.change_debt_ceiling(d_ceil=0)
    state.debt_supply()
    state.minted_redeemed()
    state.deposit(n=5, ratio=0.25, uid=4, y=5050000)
    state.debt_supply()
    state.minted_redeemed()
    state.deposit(n=14, ratio=0.5, uid=0, y=1784)
    state.debt_supply()
    state.minted_redeemed()
    state.trade(is_pump=True, r=1.0, uid=0)
    state.debt_supply()
    state.minted_redeemed()
    state.borrow_more(ratio=0.5, uid=4, y=0)
    state.teardown()


def test_cannot_create_loan(
    controller_factory,
    get_market,
    monetary_policy,
    stablecoin,
    price_oracle,
    accounts,
    get_fake_leverage,
    admin,
    collateral_token,
    market_amm,
    market_controller,
):
    fake_leverage = get_fake_leverage(collateral_token, market_controller)
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    state = BigFuzz()
    state.debt_supply()
    state.minted_redeemed()
    state.shift_oracle(dp=-0.005859375)
    state.debt_supply()
    state.minted_redeemed()
    state.deposit(n=5, ratio=0.5, uid=0, y=11585)
    state.teardown()
