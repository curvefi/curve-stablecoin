import boa
from hypothesis import assume, event, note, target
from hypothesis.stateful import rule
from hypothesis.strategies import data, integers

from tests.fuzz.stateful.stateful_base import LlamalendStatefulBase
from tests.fuzz.stateful.test_controller_stateful import ControllerStateful
from tests.fuzz.stateful.test_lend_controller_stateful import LendControllerStateful
from tests.fuzz.strategies import loan_amounts_for_create, ticks
from tests.utils import max_approve


class TargetedMetricsMixin:
    def ensure_loan_near_active_band(self, data, label: str):
        if self.users:
            return

        N = data.draw(integers(min_value=5, max_value=20), label=f"{label}_N")
        _user_label, user = self.new_borrower(label)
        collateral_unit = 10 ** int(self.collateral_token.decimals())
        collateral = data.draw(
            integers(
                min_value=1_000 * collateral_unit,
                max_value=1_000_000 * collateral_unit,
            ),
            label=f"{label}_collateral",
        )
        max_debt = int(self.controller.max_borrowable(collateral, N))
        assume(max_debt > 1)
        debt_bps = data.draw(
            integers(min_value=9_000, max_value=10_000),
            label=f"{label}_debt_bps",
        )

        for candidate_bps in (debt_bps, 10_000, 9_900, 9_500, 9_000, 8_500, 8_000):
            debt = max_debt * candidate_bps // 10_000
            if debt <= 0:
                continue
            try:
                self.create_loan(user, collateral, debt, N)
            except boa.BoaError:
                continue

            event("stateful:create_loan")
            event(f"stateful:{label}:seeded_loan")
            event(f"stateful:{label}:seeded_loan:{candidate_bps}_bps")
            return

        assume(False)

    def teardown(self):
        target(self.target_amm_volume, label="amm_volume_18")
        target(self.target_max_oracle_jump_bps, label="oracle_jump_bps")
        target(self.target_max_active_band_move, label="active_band_move")
        super().teardown()


class VaultDepositorTargetMixin:
    target_vault_depositor_goal = 100

    def initialize_vault(self, market):
        super().initialize_vault(market)
        self.target_vault_deposit_steps = 0
        self.target_vault_depositors_created = 0

    def draw_vault_deposit_amount(self, data, user_label: str, user: str):
        max_deposit = int(self.vault.maxDeposit(user))
        assume(max_deposit > 0)

        min_required = self.min_vault_deposit()
        token_decimals = int(self.vault_borrowed_token.decimals())
        upper_bound = min(max_deposit, 10**6 * 10**token_decimals)
        assume(min_required <= upper_bound)

        return data.draw(
            integers(min_value=min_required, max_value=upper_bound),
            label=f"target_deposit_amount({user_label})",
        )

    def teardown(self):
        depositors = len(self.seen_vault_users)
        target(min(depositors, self.target_vault_depositor_goal), label="vault_depositors")

        density_bps = (
            self.target_vault_depositors_created * 10_000
            // self.target_vault_deposit_steps
            if self.target_vault_deposit_steps
            else 0
        )
        target(density_bps, label="vault_depositors_per_deposit_step_bps")

        goal_score = -abs(depositors - self.target_vault_depositor_goal)
        target(goal_score, label="vault_depositor_goal_score")
        super().teardown()


class BorrowerTargetMixin:
    target_borrower_goal = 100

    def initialize_market(self, market):
        super().initialize_market(market)
        self.target_borrower_steps = 0
        self.target_borrowers_created = 0

    def teardown(self):
        borrowers = len(self.seen_borrowers)
        target(min(borrowers, self.target_borrower_goal), label="borrowers")

        density_bps = (
            self.target_borrowers_created * 10_000 // self.target_borrower_steps
            if self.target_borrower_steps
            else 0
        )
        target(density_bps, label="borrowers_per_create_step_bps")

        goal_score = -abs(borrowers - self.target_borrower_goal)
        target(goal_score, label="borrower_goal_score")
        super().teardown()


class AmmVolumeTargetStateful(TargetedMetricsMixin, LlamalendStatefulBase):
    def ensure_loan_for_trade(self, data):
        self.ensure_loan_near_active_band(data, "amm_exchange")

    def trade_for_price_move(self, data):
        current_price = int(self.amm.get_p())
        multiplier_bps = data.draw(
            integers(min_value=8_000, max_value=20_000),
            label="amm_target_price_multiplier_bps",
        )

        target_prices = [
            max(current_price * multiplier_bps // 10_000, 1),
            max(current_price * 11 // 10, 1),
            max(current_price * 13 // 10, 1),
            max(current_price * 2, 1),
            max(current_price * 9 // 10, 1),
            max(current_price * 8 // 10, 1),
        ]
        for target_price in target_prices:
            try:
                amount, is_pump = self.amm.get_amount_for_price(target_price)
            except boa.BoaError:
                continue
            if amount > 0:
                amount_bps = data.draw(
                    integers(min_value=1_000, max_value=10_000),
                    label="amm_trade_amount_bps",
                )
                amount = max(int(amount) * amount_bps // 10_000, 1)
                return (0 if is_pump else 1), amount, target_price

        assume(False)

    @rule(data=data())
    def amm_exchange(self, data):
        note("[AMM EXCHANGE]")
        self.ensure_loan_for_trade(data)

        i, amount, target_price = self.trade_for_price_move(data)
        j = 1 - i
        token = self.borrowed_token if i == 0 else self.collateral_token

        try:
            expected_out = self.amm.get_dy(i, j, amount)
        except boa.BoaError:
            assume(False)
        assume(expected_out > 0)

        trader = boa.env.generate_address("amm_volume_trader")
        boa.deal(token, trader, token.balanceOf(trader) + amount)

        band_before = int(self.amm.active_band())
        with boa.env.prank(trader):
            max_approve(token, self.amm.address)
            spent, _ = self.amm.exchange(i, j, amount, 0)
        band_after = int(self.amm.active_band())

        self.record_amm_volume(i, int(spent))
        self.record_active_band_move(band_before, band_after)
        note(
            f"amm_exchange: i={i}, amount={amount}, target_price={target_price}, "
            f"expected_out={expected_out}, spent={spent}, band_before={band_before}, "
            f"band_after={band_after}"
        )
        event("stateful:amm_exchange")
        if i == 0:
            event("stateful:amm_exchange:borrowed_to_collateral")
        else:
            event("stateful:amm_exchange:collateral_to_borrowed")
        if band_after != band_before:
            event("stateful:amm_exchange:band_move")


class PriceJumpTargetStateful(TargetedMetricsMixin, LlamalendStatefulBase):
    @rule(data=data(), multiplier_bps=integers(min_value=5_000, max_value=20_000))
    def oracle_price_jump(self, data, multiplier_bps):
        note("[ORACLE PRICE JUMP]")
        self.ensure_loan_near_active_band(data, "oracle_jump")

        price_before = int(self.price_oracle.price())
        price_after = max(price_before * multiplier_bps // 10_000, 1)
        band_before = int(self.amm.active_band())

        with boa.env.prank(self.admin):
            self.price_oracle.set_price(price_after)

        band_after = int(self.amm.active_band())
        self.record_oracle_jump(price_before, price_after)
        self.record_active_band_move(band_before, band_after)

        event("stateful:oracle_jump")
        if price_after > price_before:
            event("stateful:oracle_jump:up")
        elif price_after < price_before:
            event("stateful:oracle_jump:down")
        else:
            event("stateful:oracle_jump:flat")
        if band_after != band_before:
            event("stateful:oracle_jump:band_move")


class MarketStressTargetStateful(AmmVolumeTargetStateful, PriceJumpTargetStateful):
    pass


class VaultDepositorTargetStateful(VaultDepositorTargetMixin, LendControllerStateful):
    @rule(data=data())
    def deposit_many(self, data):
        note("[DEPOSIT MANY]")
        self.target_vault_deposit_steps += 1

        remaining = max(
            self.target_vault_depositor_goal - len(self.seen_vault_users), 1
        )
        batch_size = data.draw(
            integers(min_value=1, max_value=min(8, remaining)),
            label="target_deposit_batch_size",
        )

        for _ in range(batch_size):
            user_label, user = self.new_vault_user("target_vault_user")
            amount = self.draw_vault_deposit_amount(data, user_label, user)
            self.deposit_to_vault(user, amount)
            self.target_vault_depositors_created += 1
            event("stateful:deposit")
            event("stateful:deposit:targeted")

        depositors = len(self.seen_vault_users)
        event("stateful:deposit_many")
        if depositors >= self.target_vault_depositor_goal:
            event("stateful:depositors:goal_reached")
        elif depositors >= self.target_vault_depositor_goal // 2:
            event("stateful:depositors:half_goal")


class BorrowerTargetStateful(BorrowerTargetMixin, ControllerStateful):
    @rule(data=data())
    def create_many_loans(self, data):
        note("[CREATE MANY LOANS]")
        self.target_borrower_steps += 1

        remaining = max(self.target_borrower_goal - len(self.seen_borrowers), 1)
        batch_size = data.draw(
            integers(min_value=1, max_value=min(8, remaining)),
            label="target_borrower_batch_size",
        )

        for _ in range(batch_size):
            N = data.draw(ticks, label="target_borrower_N")
            user_label, user = self.new_borrower("target_borrower")
            collateral, debt = data.draw(
                loan_amounts_for_create(self.controller, N),
                label=f"target_borrower_loan_amounts({user_label})",
            )
            self.create_loan(user, collateral, debt, N)
            self.target_borrowers_created += 1
            event("stateful:create_loan")
            event("stateful:create_loan:targeted")

        borrowers = len(self.seen_borrowers)
        event("stateful:create_many_loans")
        if borrowers >= self.target_borrower_goal:
            event("stateful:borrowers:goal_reached")
        elif borrowers >= self.target_borrower_goal // 2:
            event("stateful:borrowers:half_goal")


TestAmmVolumeTarget = AmmVolumeTargetStateful.TestCase
TestPriceJumpTarget = PriceJumpTargetStateful.TestCase
TestMarketStressTarget = MarketStressTargetStateful.TestCase
TestVaultDepositorTarget = VaultDepositorTargetStateful.TestCase
TestBorrowerTarget = BorrowerTargetStateful.TestCase
