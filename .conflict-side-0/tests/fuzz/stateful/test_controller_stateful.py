from decimal import Decimal
from hypothesis import event, note, assume
from hypothesis.strategies import (
    composite,
    integers,
    decimals,
    SearchStrategy,
    data,
    sampled_from,
)
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    rule,
    precondition,
    invariant,
)

import boa

from tests.fuzz.strategies import mint_markets, ticks
from tests.utils.deployers import AMM_DEPLOYER, ERC20_MOCK_DEPLOYER, STABLECOIN_DEPLOYER
from tests.utils.constants import (
    MAX_UINT256,
    WAD,
)


def token_amounts(
    decimal_places: int, min_value: int = 0, max_value: int = None
) -> SearchStrategy[int]:
    decs = decimals(
        min_value=min_value,
        max_value=max_value,
        allow_nan=False,
        allow_infinity=False,
        places=decimal_places,
    )

    def strip_point_to_int(d: Decimal) -> int:
        t = d.as_tuple()  # (sign, digits, exponent)
        # Join all significant digits; if exponent > 0, append that many zeros.
        # If exponent <= 0, we just drop the point (no padding).
        digits = "".join(map(str, t.digits)) or "0"
        zeros = "0" * max(t.exponent, 0)
        return int(digits + zeros)

    return decs.map(strip_point_to_int)


@composite
def loan_amounts_for_create(draw, controller, N: int) -> tuple[int, int]:
    """
    Draw a (collateral, debt) pair valid for Controller.create_loan given N.

    - collateral is drawn using `token_amounts` based on the collateral token's decimals.
    - debt is drawn in [1, max_borrowable(collateral, N)] so `_calculate_debt_n1` won't revert.
    """
    collateral_token = ERC20_MOCK_DEPLOYER.at(controller.collateral_token())
    token_decs = collateral_token.decimals()

    # Draw collateral with bounded range to reduce extreme ratios
    collateral = draw(token_amounts(token_decs, min_value=1, max_value=1_000_000))

    # Compute an upper bound for debt using both the on-chain view and LTV
    view_cap = controller.max_borrowable(collateral, N)

    # LTV-based cap: debt <= collateral_value * (1 - loan_discount)
    loan_discount = controller.loan_discount()
    ltv = max(WAD - loan_discount, 0)

    # Precision scale factors from token decimals
    borrowed_token = ERC20_MOCK_DEPLOYER.at(controller.borrowed_token())
    borrowed_decs = borrowed_token.decimals()
    col_prec = 10 ** (18 - int(token_decs))
    bor_prec = 10 ** (18 - int(borrowed_decs))

    # Price at 1e18 from AMM
    price = AMM_DEPLOYER.at(controller.amm()).price_oracle()

    collateral_value_18 = (collateral * col_prec * price) // WAD
    ltv_cap_18 = (collateral_value_18 * ltv) // WAD
    ltv_cap = ltv_cap_18 // bor_prec

    max_debt = min(view_cap, ltv_cap)

    # Skip zero-cap cases
    assume(max_debt > 0)

    # Draw debt within [max(view_cap/32, 1), view_cap] to avoid tiny-debt cases
    # that push n1 beyond exponent safety bounds in AMM.p_oracle_up
    min_debt = max(1, max_debt // 32)
    debt = draw(integers(min_value=min_debt, max_value=max_debt))
    return collateral, debt


@composite
def loan_increments_for_borrow_more(
    draw,
    controller,
    user: str,
    N: int,
    collateral0: int,
    debt0: int,
) -> tuple[int, int]:
    """
    Draw (d_collateral, d_debt) increments for a safe borrow_more call.

    - d_collateral: decimals-aware collateral increment with bounded range.
    - d_debt: drawn within a safe fraction of the available headroom derived from
      controller.max_borrowable(collateral0 + d_collateral, N, debt0, user).
    """
    collateral_token = ERC20_MOCK_DEPLOYER.at(controller.collateral_token())
    token_decs = collateral_token.decimals()

    # Reasonable collateral increment to avoid extreme ratios
    d_collateral = draw(token_amounts(token_decs, min_value=1, max_value=1_000_000))

    # Compute available headroom and draw delta debt safely within it
    cap_total = controller.max_borrowable(collateral0 + d_collateral, N, debt0, user)
    assume(cap_total > debt0)
    delta_cap = cap_total - debt0
    min_delta = max(1, delta_cap // 32)
    d_debt = draw(integers(min_value=min_delta, max_value=delta_cap))

    return d_collateral, d_debt


# ---------------- mint market via Protocol ----------------


# ------------ controller interaction params -------------


class ControllerStateful(RuleBasedStateMachine):
    @initialize(market=mint_markets())
    def _initialize(self, market):
        # Unpack market artifacts
        self.controller = market["controller"]
        self.amm = market["amm"]
        self.users = []
        self.collateral_token = ERC20_MOCK_DEPLOYER.at(
            self.controller.collateral_token()
        )
        self.borrowed_token = STABLECOIN_DEPLOYER.at(self.controller.borrowed_token())
        self.borrowed_token.approve(self.controller.address, MAX_UINT256)

    @rule(N=ticks, data=data())
    def create_loan_rule(self, N, data):
        note("[CREATE LOAN]")
        # New user per invocation
        user_label = f"user_{len(self.users)}"
        user = boa.env.generate_address(user_label)

        # Draw a valid (collateral, debt) pair for this controller and N
        collateral, debt = data.draw(
            loan_amounts_for_create(self.controller, N),
            label=f"loan_amounts_for_create({user_label})",
        )

        # Deal collateral on site and approve controller
        note(
            f"creating loan: N={N}, user={user_label}, collateral={collateral}, debt={debt}, "
            f"collat_decs={self.collateral_token.decimals()}, loan_discount={self.controller.loan_discount()}"
        )
        boa.deal(self.collateral_token, user, collateral)
        with boa.env.prank(user):
            self.collateral_token.approve(self.controller.address, MAX_UINT256)
            self.controller.create_loan(collateral, debt, N)

        self.users.append(user)

    @invariant()
    def time_passes(self):
        # Snapshot current debts for tracked users
        before = {u: self.controller.debt(u) for u in self.users}

        # Advance time and update AMM rate based on monetary policy
        dt = 3600  # one hour
        boa.env.time_travel(dt)
        self.controller.save_rate()

        # Debts should not decrease with time
        for u, d0 in before.items():
            d1 = self.controller.debt(u)
            assert d1 >= d0

    @precondition(lambda self: len(self.users) > 0)
    @rule(data=data())
    def repay_rule(self, data):
        note("[REPAY]")
        # Pick a random tracked user (open position invariant ensures this is valid)
        user = data.draw(sampled_from(self.users), label="repay_user")

        # Current debt and repay amount in [1, debt]
        debt = self.controller.debt(user)
        assume(debt > 0)
        repay_amount = data.draw(
            integers(min_value=1, max_value=debt), label="repay_amount"
        )

        # Ensure user has enough borrowed tokens and allowance
        borrowed = STABLECOIN_DEPLOYER.at(self.controller.borrowed_token())
        boa.deal(borrowed, user, repay_amount)
        with boa.env.prank(user):
            borrowed.approve(self.controller.address, MAX_UINT256)
            self.controller.repay(repay_amount)

        # If fully repaid, remove from tracking list
        if not self.controller.loan_exists(user):
            self.users.remove(user)

        note(f"repay: user={user}, debt_before={debt}, repay_amount={repay_amount}")

    @precondition(lambda self: len(self.users) > 0)
    @rule(data=data())
    def borrow_more_rule(self, data):
        note("[BORROW MORE]")
        # Pick a random tracked user and ensure position is healthy
        user = data.draw(sampled_from(self.users), label="borrow_more_user")
        assume(self.controller.health(user, False) > 0)

        # Fetch current state
        collateral0, _x0, debt0, N = self.controller.user_state(user)

        # Draw increments using the shared strategy
        d_collateral, d_debt = data.draw(
            loan_increments_for_borrow_more(
                self.controller, user, N, collateral0, debt0
            ),
            label="borrow_more_increments",
        )

        # Fund collateral and call borrow_more as the user
        boa.deal(self.collateral_token, user, d_collateral)
        with boa.env.prank(user):
            # Approve is already set at creation, but re-approve is harmless
            self.collateral_token.approve(self.controller.address, MAX_UINT256)
            self.controller.borrow_more(d_collateral, d_debt)

    @precondition(lambda self: len(self.users) > 0)
    @rule(data=data())
    def remove_collateral_rule(self, data):
        note("[REMOVE COLLATERAL]")

        # Pick a random tracked user and ensure position is healthy
        user = data.draw(sampled_from(self.users), label="remove_collateral_user")

        # Read current state
        collateral, _x, debt, N = self.controller.user_state(user)

        # Compute the maximum removable collateral using min_collateral
        min_coll = self.controller.min_collateral(debt, N, user)
        assert collateral >= min_coll
        removable = collateral - min_coll

        if removable == 0:
            event(f"user {user} has no removable collateral")
            return

        # Draw a safe removal amount, avoid edge rounding by not always taking full
        min_remove = max(1, removable // 64)
        d_collateral = data.draw(
            integers(min_value=min_remove, max_value=removable),
            label="remove_collateral_amount",
        )

        # Call as user
        with boa.env.prank(user):
            self.controller.remove_collateral(d_collateral)

    @invariant()
    def open_users_invariant(self):
        # On-chain enumeration of open loans
        n = self.controller.n_loans()
        onchain_users = [self.controller.loans(i) for i in range(n)]
        # Ensure tracking matches on-chain state
        assert set(onchain_users) == set(self.users)
        assert len(onchain_users) == len(self.users)
        for u in self.users:
            assert self.controller.loan_exists(u)

    @precondition(lambda self: len(self.users) > 0)
    @invariant()
    def liquidate(self):
        positions = self.controller.users_to_liquidate(0, len(self.users))
        if len(positions) == 0:
            return

        note("[HARD LIQUIDATE]")
        for pos in positions:
            note(
                f"liquidating user {pos.user} with health {self.controller.health(pos.user, True)}"
            )
            required = self.controller.tokens_to_liquidate(pos.user, WAD)
            if required > 0:
                boa.deal(self.borrowed_token, boa.env.eoa, required)
            self.controller.liquidate(pos.user, 0, WAD)

        assert len(self.controller.users_to_liquidate(0, len(self.users))) == 0

        n = self.controller.n_loans()
        self.users = [self.controller.loans(i) for i in range(n)]


TestControllerStateful = ControllerStateful.TestCase
