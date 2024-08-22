import boa
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, run_state_machine_as_test, rule, invariant
from ..conftest import approx


class StateMachine(RuleBasedStateMachine):
    user_id = st.integers(min_value=0, max_value=4)
    deposit_pct = st.floats(min_value=0.001, max_value=1.0)
    borrow_pct = st.floats(min_value=0.001, max_value=1.0)
    withdraw_pct = st.floats(min_value=0.001, max_value=1.0)
    repay_pct = st.floats(min_value=0.001, max_value=1.0)
    target_band_pct = st.floats(min_value=0.0, max_value=1.0)
    target_price_pct = st.floats(min_value=0.0, max_value=1.0)
    time = st.integers(min_value=300, max_value=86400 * 90)
    lock_time = st.integers(min_value=86400 * 7, max_value=86400 * 365 * 4)

    def __init__(self):
        super().__init__()
        self.checkpoint_supply = 0
        self.checkpoint_working_supply = 0
        self.checkpoint_rate = self.crv.rate()
        self.integrals = {addr: {
            "checkpoint": boa.env.evm.patch.timestamp,
            "integral": 0,
            "balance": 0,
            "working_balance": 0,
            "boost": 0,
        } for addr in self.accounts[:5]}

    def update_integrals(self, user):
        # Update rewards
        t1 = boa.env.evm.patch.timestamp
        t_epoch = self.crv.start_epoch_time_write(sender=self.admin)
        rate1 = self.crv.rate()
        for acct in self.accounts[:5]:
            integral = self.integrals[acct]
            if integral["checkpoint"] >= t_epoch:
                rate_x_time = (t1 - integral["checkpoint"]) * rate1
            else:
                rate_x_time = (t_epoch - integral["checkpoint"]) * self.checkpoint_rate + (t1 - t_epoch) * rate1
            if self.checkpoint_working_supply > 0:
                integral["integral"] += rate_x_time * integral["working_balance"] // self.checkpoint_working_supply
            integral["checkpoint"] = t1
            integral["balance"] = self.market_amm.get_sum_xy(acct)[1]
        self.checkpoint_supply = self.collateral_token.balanceOf(self.market_amm) - self.market_amm.admin_fees_y()
        self.checkpoint_rate = rate1

        # Update working balance and supply
        for acct in self.accounts[:5]:
            voting_balance = self.voting_escrow_delegation_mock.adjusted_balance_of(acct)
            voting_total = self.voting_escrow.totalSupply()
            integral = self.integrals[acct]
            if acct == user and self.market_controller.user_state(user)[1] == 0:  # user is not underwater
                lim = integral["balance"] * 40 // 100
                if voting_total > 0:
                    lim += self.checkpoint_supply * voting_balance // voting_total * 60 // 100
                lim = min(integral["balance"], lim)

                old_bal = integral["working_balance"]
                integral["working_balance"] = lim
                self.checkpoint_working_supply += lim - old_bal
                if integral["balance"] > 0:
                    integral["boost"] = lim / integral["balance"]
                else:
                    integral["boost"] = 0
            else:
                old_bal = integral["working_balance"]
                integral["working_balance"] = int(integral["balance"] * integral["boost"])
                self.checkpoint_working_supply += integral["working_balance"] - old_bal

    @rule(uid=user_id, deposit_pct=deposit_pct, borrow_pct=borrow_pct)
    def deposit(self, uid, deposit_pct, borrow_pct):
        """
        Make a deposit into the `LiquidityGauge` contract.

        Because of the upper bound of `st_value` relative to the initial account
        balances, this rule should never fail.
        """
        user = self.accounts[uid]
        with boa.env.prank(user):
            balance = self.collateral_token.balanceOf(user)
            deposit_amount = min(int(balance * deposit_pct), balance)
            collateral_in_amm, stablecoin_in_amm, debt, __ = self.market_controller.user_state(user)
            max_borrowable = self.market_controller.max_borrowable(deposit_amount + collateral_in_amm, 10, debt)
            borrow_amount = min(int((max_borrowable - debt) * borrow_pct), max_borrowable - debt)
            i = 1
            while True:
                try:
                    self.market_controller.calculate_debt_n1(collateral_in_amm + deposit_amount, debt + borrow_amount, 10)
                    break
                except Exception:
                    if i == 100:
                        break
                    i += 1
                    borrow_amount = borrow_amount * (100 - i) // 100
            is_underwater = stablecoin_in_amm > 0
            if borrow_amount <= 0 or is_underwater:
                return

            if self.market_controller.loan_exists(user):
                self.market_controller.borrow_more(deposit_amount, borrow_amount)
            else:
                self.market_controller.create_loan(deposit_amount, borrow_amount, 10)
            assert self.collateral_token.balanceOf(user) == balance - deposit_amount

            self.update_integrals(user)
            r1 = self.boosted_lm_callback.integrate_fraction(user)
            r2 = self.integrals[user]["integral"]
            assert (r1 > 0) == (r2 > 0)
            if r1 > 0:
                assert approx(r1, r2, 1e-13) or abs(r1 - r2) < 100

    @rule(uid=user_id, withdraw_pct=withdraw_pct, repay_pct=repay_pct)
    def withdraw(self, uid, withdraw_pct, repay_pct):
        """
        Attempt to withdraw from the `LiquidityGauge` contract.
        """
        user = self.accounts[uid]
        with boa.env.prank(user):
            balance = self.collateral_token.balanceOf(user)
            collateral_in_amm, stablecoin_in_amm, debt, __ = self.market_controller.user_state(user)
            is_underwater = stablecoin_in_amm > 0
            if collateral_in_amm == 0:
                return

            withdraw_amount = 0
            if repay_pct == 1:
                self.market_controller.repay(debt)
                withdraw_amount = collateral_in_amm
            elif self.market_controller.health(user) > 0:
                repay_amount = int(debt * repay_pct)
                self.market_controller.repay(repay_amount)
                if is_underwater:
                    # Underwater repay does not trigger callback, so we call checkpoint manually to pass checks below
                    self.boosted_lm_callback.user_checkpoint(user)
                else:
                    withdraw_amount = int(collateral_in_amm * withdraw_pct)
                    min_collateral_required = self.market_controller.min_collateral(debt - repay_amount, 10)
                    withdraw_amount = min(collateral_in_amm - min_collateral_required, withdraw_amount) * 99 // 100
                    withdraw_amount = max(withdraw_amount, 0)
                    if withdraw_amount > 0:
                        self.market_controller.remove_collateral(withdraw_amount)
            else:
                # We call checkpoint manually to pass checks below
                self.boosted_lm_callback.user_checkpoint(user)
            self.update_integrals(user)

            assert self.collateral_token.balanceOf(user) == balance + withdraw_amount

            r1 = self.boosted_lm_callback.integrate_fraction(user)
            r2 = self.integrals[user]["integral"]
            assert (r1 > 0) == (r2 > 0)
            if r1 > 0:
                assert approx(r1, r2, 1e-13) or abs(r1 - r2) < 100

    @rule(target_band_pct=target_band_pct, target_price_pct=target_price_pct)
    def trade(self, target_band_pct, target_price_pct):
        """
        Makes a trade in LLAMMA.
        """
        with boa.env.prank(self.chad):
            available_bands = []
            for acct in self.accounts[:5]:
                border_bands = self.market_amm.read_user_tick_numbers(acct)
                available_bands += [] if border_bands[0] == border_bands[1] else list(range(border_bands[0], border_bands[1] + 1))
            p_o = self.market_amm.price_oracle()
            upper_bands = sorted(list(filter(lambda band: self.market_amm.p_oracle_down(band) > p_o, available_bands)))[-5:]
            lower_bands = sorted(list(filter(lambda band: self.market_amm.p_oracle_up(band) < p_o, available_bands)))[:5]
            available_bands = upper_bands + lower_bands
            if len(available_bands) > 0:
                target_band = available_bands[int(target_band_pct * (len(available_bands) - 1))]
                p_up = self.market_amm.p_oracle_up(target_band)
                p_down = self.market_amm.p_oracle_down(target_band)
                p_target = int(p_down + target_price_pct * (p_up - p_down))
                self.price_oracle.set_price(p_target, sender=self.admin)
                amount, pump = self.market_amm.get_amount_for_price(p_target)
                balance = self.stablecoin.balanceOf(self.chad) if pump else self.collateral_token.balanceOf(self.chad)
                amount = min(amount, balance)
                if amount > 0:
                    if pump:
                        self.market_amm.exchange(0, 1, amount, 0)
                    else:
                        self.market_amm.exchange(1, 0, amount, 0)
                    self.update_integrals(None)

    @rule(dt=time)
    def advance_time(self, dt):
        """
        Advance the clock.
        """
        boa.env.time_travel(seconds=dt)

    @rule(uid=user_id, dt=lock_time)
    def create_lock(self, uid, dt):
        """
        Create lock in voting escrow to get boosted.
        """
        user = self.accounts[uid]
        if self.voting_escrow.locked(user)[0] == 0:
            self.voting_escrow.create_lock(10 ** 20, boa.env.evm.patch.timestamp + dt, sender=user)

    @rule(uid=user_id)
    def withdraw_from_ve(self, uid):
        """
        Withdraw expired lock from voting escrow.
        """
        user = self.accounts[uid]
        if 0 < self.voting_escrow.locked__end(user) < boa.env.evm.patch.timestamp:
            self.voting_escrow.withdraw(sender=user)

    @rule(uid=user_id)
    def checkpoint(self, uid):
        """
        Create a new user checkpoint.
        """
        user = self.accounts[uid]
        with boa.env.prank(user):
            self.boosted_lm_callback.user_checkpoint(user)
            self.update_integrals(user)
            r1 = self.boosted_lm_callback.integrate_fraction(user)
            r2 = self.integrals[user]["integral"]
            assert (r1 > 0) == (r2 > 0)
            if r1 > 0:
                assert approx(r1, r2, 1e-13) or abs(r1 - r2) < 100

    @invariant()
    def invariant_collateral(self):
        """
        Validate expected balances against actual balances and
        expected total supply against actual total supply.
        """
        for account, integral in self.integrals.items():
            y1 = self.boosted_lm_callback.user_collateral(account)
            y2 = integral["balance"]
            assert approx(y1, y2, 1e-14) or abs(y1 - y2) < 100000  # Seems ok for 18 decimals

        Y1 = self.boosted_lm_callback.total_collateral()
        Y2 = sum([i["balance"] for i in self.integrals.values()])
        assert approx(Y1, Y2, 1e-13) or abs(Y1 - Y2) < 100000  # Seems ok for 18 decimals

    @invariant()
    def invariant_working_collateral(self):
        """
        Validate expected working balances against actual working balances and
        expected working supply against actual working supply.
        """
        for account, integral in self.integrals.items():
            y1 = self.boosted_lm_callback.working_collateral(account)
            y2 = integral["working_balance"]
            assert approx(y1, y2, 1e-14) or abs(y1 - y2) < 100000  # Seems ok for 18 decimals

        Y1 = self.boosted_lm_callback.working_supply()
        Y2 = sum([i["working_balance"] for i in self.integrals.values()])
        assert approx(Y1, Y2, 1e-13) or abs(Y1 - Y2) < 100000  # Seems ok for 18 decimals

    def teardown(self):
        """
        Final check to ensure that all balances may be withdrawn.
        """
        for account, integral in ((k, v) for k, v in self.integrals.items() if v):
            initial_balance = self.collateral_token.balanceOf(account)
            collateral_in_amm = integral["balance"]
            debt = self.market_controller.user_state(account)[2]
            self.market_controller.repay(debt, sender=account)
            self.update_integrals(account)

            assert not self.market_controller.loan_exists(account)
            assert self.collateral_token.balanceOf(account) == initial_balance + collateral_in_amm

            r1 = self.boosted_lm_callback.integrate_fraction(account)
            r2 = self.integrals[account]["integral"]
            assert (r1 > 0) == (r2 > 0)
            if r1 > 0:
                assert approx(r1, r2, 1e-13) or abs(r1 - r2) < 100


def test_state_machine(
        accounts,
        admin,
        chad,
        stablecoin,
        collateral_token,
        crv,
        boosted_lm_callback,
        gauge_controller,
        market_controller,
        market_amm,
        price_oracle,
        voting_escrow,
        voting_escrow_delegation_mock,
):
    for acct in accounts[:5]:
        with boa.env.prank(admin):
            collateral_token._mint_for_testing(acct, 1000 * 10**18)
            crv.transfer(acct, 10 ** 20)

        with boa.env.prank(acct):
            collateral_token.approve(market_controller, 2 ** 256 - 1)
            crv.approve(voting_escrow, 2 ** 256 - 1)

    # Wire up Gauge to the controller to have proper rates and stuff
    with boa.env.prank(admin):
        gauge_controller.add_type("crvUSD Market")
        gauge_controller.change_type_weight(0, 10 ** 18)
        gauge_controller.add_gauge(boosted_lm_callback.address, 0, 10 ** 18)

    boa.env.time_travel(seconds=7 * 86400)

    StateMachine.TestCase.settings = settings(max_examples=400, stateful_step_count=50)
    for k, v in locals().items():
        setattr(StateMachine, k, v)
    run_state_machine_as_test(StateMachine)
