"""
Amounts are drawn as 1e18-scaled fractions and mapped onto state-dependent
bounds inside the loop, since hypothesis has to pick every value up front.
"""

import boa
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.integration.lm_callback.utils import (
    ONE,
    RATE_REDUCTION_TIME,
    WEEK,
    YEAR,
    accrue,
    chance,
    scale,
)
from tests.utils.constants import MAX_UINT256

N_ITERATIONS = 20
N_BANDS = 10

FRACTION = st.integers(min_value=0, max_value=ONE)

# `create_loan` / `borrow_more` need a positive debt, and the AMM needs > 100 wei
# of collateral per band, so unlike `randrange(1, ...)` these are floored away
# from dust - hypothesis probes the ends of every range, plain randomness never did.
MIN_DEPOSIT = 10**16
DEBT_FRACTION = st.integers(min_value=10**16, max_value=ONE)  # 20x - 2000x collateral


USER_STEP = st.fixed_dictionaries(
    {
        "withdraw": chance(50),
        "amount": FRACTION,  # withdrawn share of the collateral in the AMM
        "repay": FRACTION,  # repaid share of the debt (capped at 99% as before)
        "deposit": FRACTION,  # deposited share of the wallet balance
        "debt": DEBT_FRACTION,
    }
)

ONE_USER_STEP = USER_STEP

TWO_USER_STEP = st.fixed_dictionaries(
    {
        "act_borrower1": chance(20),
        "dt_action": st.integers(min_value=1, max_value=YEAR // 5 - 1),
        "dt_claim": st.integers(min_value=1, max_value=YEAR // 20 - 1),
        "checkpoint_borrower1": chance(50),
        "checkpoint_borrower2": chance(50),
        "borrower1": USER_STEP,
        "borrower2": USER_STEP,
    }
)


def act(controller, lm_callback, user, step, deposit_amount, allow_withdraw):
    """Deposit or withdraw for `user`; returns the signed change of its collateral."""
    collateral_in_amm, _, debt, __ = controller.user_state(user)
    assert collateral_in_amm == lm_callback.user_collateral(user)

    with boa.env.prank(user):
        if allow_withdraw and step["withdraw"] and collateral_in_amm > 0:
            amount = scale(step["amount"], 1, collateral_in_amm)
            if amount == collateral_in_amm:
                controller.repay(debt)
                return -collateral_in_amm

            repay_amount = debt * step["repay"] * 99 // (100 * ONE)
            if repay_amount > 0:
                controller.repay(repay_amount)
            min_collateral_required = controller.min_collateral(
                debt - repay_amount, N_BANDS
            )
            remove_amount = max(
                min(collateral_in_amm - min_collateral_required, amount), 0
            )
            if remove_amount > 0:
                controller.remove_collateral(remove_amount)
            elif repay_amount == 0:
                # Nothing was sent, so the callback would not have checkpointed here
                # while the model does - their cached CRV epochs would drift apart
                lm_callback.user_checkpoint(user)
            return -remove_amount

        new_debt = deposit_amount * 2000 * step["debt"] // ONE
        if controller.loan_exists(user):
            controller.borrow_more(deposit_amount, new_debt)
        else:
            controller.create_loan(deposit_amount, new_debt, N_BANDS)
        return deposit_amount


@given(
    steps=st.lists(ONE_USER_STEP, min_size=N_ITERATIONS, max_size=N_ITERATIONS),
)
@settings(max_examples=25)
def test_gauge_integral_one_user(
    admin, collateral_token, borrowed_token, crv, lm_callback, controller, minter, steps
):
    with boa.env.anchor():
        borrower = boa.env.generate_address("borrower")
        boa.deal(collateral_token, borrower, 1000 * 10**18)
        collateral_token.approve(controller, MAX_UINT256, sender=borrower)
        borrowed_token.approve(controller, MAX_UINT256, sender=borrower)

        boa.env.time_travel(seconds=WEEK)

        borrower_staked = 0
        integral = 0  # ∫(balance * rate(t) / totalSupply(t) dt)
        checkpoint = boa.env.timestamp
        checkpoint_rate = crv.rate()
        checkpoint_future_epoch = crv.start_epoch_time() + RATE_REDUCTION_TIME
        checkpoint_supply = 0
        checkpoint_balance = 0

        def update_integral():
            nonlocal \
                checkpoint, \
                checkpoint_rate, \
                checkpoint_future_epoch, \
                integral, \
                checkpoint_balance, \
                checkpoint_supply

            t1 = boa.env.timestamp
            rate_x_time, checkpoint_rate, checkpoint_future_epoch = accrue(
                crv, checkpoint, t1, checkpoint_rate, checkpoint_future_epoch
            )
            if checkpoint_supply > 0:
                integral += rate_x_time * checkpoint_balance // checkpoint_supply
            checkpoint = t1
            checkpoint_supply = lm_callback.total_collateral()
            checkpoint_balance = lm_callback.user_collateral(borrower)

        # Gaps grow twice as fast as the 40-iteration original, so the last claim
        # interval still exceeds RATE_REDUCTION_TIME - that is the only place where
        # a checkpoint skips a whole CRV epoch (see `accrue`)
        for i, step in enumerate(steps):
            boa.env.time_travel(seconds=6 * (i + 1) * 86400)

            borrower_staked += act(
                controller,
                lm_callback,
                borrower,
                step,
                deposit_amount=collateral_token.balanceOf(borrower) // 5,
                allow_withdraw=i > 0,
            )
            update_integral()

            assert lm_callback.user_collateral(borrower) == borrower_staked
            assert lm_callback.total_collateral() == borrower_staked

            dt = (i + 1) * 20 * 86400
            boa.env.time_travel(seconds=dt)

            lm_callback.user_checkpoint(borrower, sender=borrower)
            update_integral()
            crv_reward = lm_callback.integrate_fraction(borrower)
            assert crv_reward == pytest.approx(integral, rel=1e-14)
            minter.mint(lm_callback.address, sender=borrower)
            assert crv.balanceOf(borrower) == crv_reward


@given(
    steps=st.lists(TWO_USER_STEP, min_size=N_ITERATIONS, max_size=N_ITERATIONS),
)
@settings(max_examples=25)
def test_gauge_integral(
    admin, collateral_token, borrowed_token, crv, lm_callback, controller, minter, steps
):
    with boa.env.anchor():
        borrower1 = boa.env.generate_address("borrower1")
        borrower2 = boa.env.generate_address("borrower2")
        for b in (borrower1, borrower2):
            boa.deal(collateral_token, b, 1000 * 10**18)
            collateral_token.approve(controller, MAX_UINT256, sender=b)
            borrowed_token.approve(controller, MAX_UINT256, sender=b)

        # gauge_relative_weight is 0 until the week boundary following add_gauge,
        # while update_integral() below assumes w == 1e18
        boa.env.time_travel(seconds=WEEK)

        borrower1_staked = 0
        borrower2_staked = 0
        integral = 0  # ∫(balance * rate(t) / totalSupply(t) dt)
        checkpoint = boa.env.timestamp
        boa.env.time_travel(blocks=1)
        checkpoint_rate = crv.rate()
        checkpoint_future_epoch = crv.start_epoch_time() + RATE_REDUCTION_TIME
        checkpoint_supply = 0
        checkpoint_balance = 0

        def update_integral():
            nonlocal \
                checkpoint, \
                checkpoint_rate, \
                checkpoint_future_epoch, \
                integral, \
                checkpoint_balance, \
                checkpoint_supply

            t1 = boa.env.timestamp
            rate_x_time, checkpoint_rate, checkpoint_future_epoch = accrue(
                crv, checkpoint, t1, checkpoint_rate, checkpoint_future_epoch
            )
            if checkpoint_supply > 0:
                integral += rate_x_time * checkpoint_balance // checkpoint_supply
            checkpoint = t1
            checkpoint_supply = lm_callback.total_collateral()
            checkpoint_balance = lm_callback.user_collateral(borrower1)

        # borrower2 always deposits or withdraws; borrower1 does so more rarely
        for i, step in enumerate(steps):
            boa.env.time_travel(seconds=step["dt_action"])

            borrower2_staked += act(
                controller,
                lm_callback,
                borrower2,
                step["borrower2"],
                deposit_amount=scale(
                    step["borrower2"]["deposit"],
                    MIN_DEPOSIT,
                    collateral_token.balanceOf(borrower2) // 10,
                ),
                allow_withdraw=i > 0,
            )
            update_integral()

            if step["act_borrower1"]:
                borrower1_staked += act(
                    controller,
                    lm_callback,
                    borrower1,
                    step["borrower1"],
                    deposit_amount=scale(
                        step["borrower1"]["deposit"],
                        MIN_DEPOSIT,
                        collateral_token.balanceOf(borrower1) // 10,
                    ),
                    allow_withdraw=True,
                )
                update_integral()

            # Checking that updating the checkpoint in the same second does nothing
            # Also everyone can update: that should make no difference, too
            if step["checkpoint_borrower1"]:
                lm_callback.user_checkpoint(borrower1, sender=borrower1)
            if step["checkpoint_borrower2"]:
                lm_callback.user_checkpoint(borrower2, sender=borrower2)

            assert lm_callback.user_collateral(borrower1) == borrower1_staked
            assert lm_callback.user_collateral(borrower2) == borrower2_staked
            assert lm_callback.total_collateral() == borrower1_staked + borrower2_staked

            dt = step["dt_claim"]
            boa.env.time_travel(seconds=dt)

            with boa.env.prank(borrower1):
                crv_balance = crv.balanceOf(borrower1)
                with boa.env.anchor():
                    crv_reward = lm_callback.claimable_tokens(borrower1)
                minter.mint(lm_callback.address)
                assert crv.balanceOf(borrower1) - crv_balance == crv_reward

                update_integral()
                assert lm_callback.integrate_fraction(borrower1) == pytest.approx(
                    integral, rel=1e-14
                )

            with boa.env.prank(borrower2):
                crv_balance = crv.balanceOf(borrower2)
                with boa.env.anchor():
                    crv_reward = lm_callback.claimable_tokens(borrower2)
                minter.mint(lm_callback.address)
                assert crv.balanceOf(borrower2) - crv_balance == crv_reward
