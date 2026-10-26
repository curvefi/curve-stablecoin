"""Reward pauses preserve earned CRV and continuous AMM/share accounting."""

import boa
import pytest

from tests.integration.lm_callback.test_emission_bounds import (
    fund,
    open_loan,
    soft_liquidate,
    start_emissions,
    weight_budget,
)
from tests.utils import filter_logs
from tests.utils.constants import ZERO_ADDRESS

WEEK = 7 * 86400


def _borrower(collateral_token, borrowed_token, controller, crv, callback, admin):
    borrower = boa.env.generate_address("borrower")
    fund(collateral_token, borrowed_token, controller, borrower)
    start_emissions(crv, callback, admin)
    open_loan(controller, borrower)
    return borrower


@pytest.mark.parametrize("killed", [False, True])
def test_only_current_factory_owner_can_set_killed(lm_callback, killed):
    non_owner = boa.env.generate_address("non_owner")
    with boa.reverts("only owner"):
        lm_callback.set_killed(killed, sender=non_owner)


def test_factory_owner_rotation(admin, lm_callback, lm_callback_factory):
    with boa.env.anchor():
        new_owner = boa.env.generate_address("new_owner")
        lm_callback.set_killed(True, sender=admin)
        lm_callback_factory.transfer_ownership(new_owner, sender=admin)
        with boa.reverts("only owner"):
            lm_callback.set_killed(False, sender=admin)
        lm_callback.set_killed(False, sender=new_owner)
        assert not lm_callback.is_killed()


def test_kill_before_attachment(
    admin, amm, controller, configurator, deploy_lm_callback
):
    with boa.env.anchor():
        callback = deploy_lm_callback(amm)
        callback.set_killed(True, sender=admin)
        assert callback.is_killed()
        assert not callback.attached() and not callback.detached()
        with boa.reverts("not attached"):
            callback.set_killed(False, sender=admin)

        configurator.set_callback(controller, callback, sender=admin)
        assert callback.is_killed()
        callback.set_killed(False, sender=admin)
        assert callback.attached() and not callback.detached()
        assert not callback.is_killed()


def test_set_killed_event_and_repeated_calls(admin, lm_callback):
    with boa.env.anchor():
        for killed in (True, True, False, False):
            lm_callback.set_killed(killed, sender=admin)
            logs = filter_logs(lm_callback, "SetKilled")
            assert len(logs) == 1
            assert logs[0].killed == killed
            assert lm_callback.is_killed() == killed


def test_pre_pause_rewards_remain_mintable(
    admin, collateral_token, borrowed_token, controller, crv, lm_callback, minter
):
    with boa.env.anchor():
        callback = lm_callback
        borrower = _borrower(
            collateral_token, borrowed_token, controller, crv, callback, admin
        )
        boa.env.time_travel(seconds=WEEK)
        assert callback.integrate_fraction(borrower) == 0  # Not settled yet.
        callback.set_killed(True, sender=admin)
        cutoff_rpc = callback.I_rpc()[0]
        callback.user_checkpoint(borrower)
        earned = callback.integrate_fraction(borrower)
        assert earned > 0
        minter.mint(callback.address, sender=borrower)
        assert minter.minted(borrower, callback.address) == earned

        boa.env.time_travel(seconds=WEEK)
        callback.user_checkpoint(borrower)
        assert callback.integrate_fraction(borrower) == earned
        assert callback.I_rpc() == (cutoff_rpc, boa.env.timestamp)


def test_resume_without_intermediate_checkpoints_excludes_pause(
    admin,
    collateral_token,
    borrowed_token,
    controller,
    crv,
    gauge_controller,
    lm_callback,
):
    with boa.env.anchor():
        callback = lm_callback
        borrower = _borrower(
            collateral_token, borrowed_token, controller, crv, callback, admin
        )
        boa.env.time_travel(seconds=WEEK)
        callback.set_killed(True, sender=admin)
        callback.user_checkpoint(borrower)
        earned = callback.integrate_fraction(borrower)
        cutoff_rpc = callback.I_rpc()[0]

        boa.env.time_travel(seconds=2 * WEEK)
        resume = boa.env.timestamp
        callback.set_killed(False, sender=admin)
        assert not callback.is_killed()
        assert callback.I_rpc() == (cutoff_rpc, resume)
        boa.env.time_travel(seconds=86400)
        callback.user_checkpoint(borrower)
        added = callback.integrate_fraction(borrower) - earned
        assert (
            0
            < added
            <= weight_budget(
                gauge_controller, callback, crv.rate(), resume, boa.env.timestamp
            )
        )


def test_deposit_during_pause_cannot_claim_historical_rewards(
    admin,
    collateral_token,
    borrowed_token,
    controller,
    crv,
    gauge_controller,
    lm_callback,
):
    with boa.env.anchor():
        callback = lm_callback
        incumbent = _borrower(
            collateral_token, borrowed_token, controller, crv, callback, admin
        )
        start = boa.env.timestamp
        boa.env.time_travel(seconds=WEEK)
        cutoff = boa.env.timestamp
        callback.set_killed(True, sender=admin)

        latecomer = boa.env.generate_address("latecomer")
        fund(collateral_token, borrowed_token, controller, latecomer)
        boa.env.time_travel(seconds=WEEK)
        open_loan(controller, latecomer)
        callback.user_checkpoint(latecomer)
        assert callback.integrate_fraction(latecomer) == 0
        callback.user_checkpoint(incumbent)
        earned = callback.integrate_fraction(incumbent)
        assert earned > 0

        resume = boa.env.timestamp
        callback.set_killed(False, sender=admin)
        boa.env.time_travel(seconds=WEEK)
        for borrower in (incumbent, latecomer):
            callback.user_checkpoint(borrower)
        budget = weight_budget(gauge_controller, callback, crv.rate(), start, cutoff)
        budget += weight_budget(
            gauge_controller, callback, crv.rate(), resume, boa.env.timestamp
        )
        assert callback.integrate_fraction(incumbent) >= earned
        assert callback.integrate_fraction(latecomer) > 0
        assert (
            sum(callback.integrate_fraction(u) for u in (incumbent, latecomer))
            <= budget
        )


def test_repay_during_pause_preserves_earned_rewards(
    admin, collateral_token, borrowed_token, controller, crv, lm_callback, minter
):
    with boa.env.anchor():
        callback = lm_callback
        borrower = _borrower(
            collateral_token, borrowed_token, controller, crv, callback, admin
        )
        boa.env.time_travel(seconds=WEEK)
        callback.set_killed(True, sender=admin)
        boa.env.time_travel(seconds=WEEK)
        controller.repay(controller.user_state(borrower)[2], sender=borrower)
        earned = callback.integrate_fraction(borrower)
        assert earned > 0
        callback.user_checkpoint(borrower)
        assert callback.integrate_fraction(borrower) == earned
        minter.mint(callback.address, sender=borrower)
        assert minter.minted(borrower, callback.address) == earned


def test_swap_during_pause_keeps_band_ratios_current(
    admin,
    collateral_token,
    borrowed_token,
    controller,
    crv,
    lm_callback,
    amm,
    trader,
    price_oracle,
):
    with boa.env.anchor():
        callback = lm_callback
        borrower = boa.env.generate_address("borrower")
        fund(collateral_token, borrowed_token, controller, borrower)
        start_emissions(crv, callback, admin)
        controller.create_loan(10**21, 2600 * 10**21, 10, sender=borrower)
        boa.env.time_travel(seconds=WEEK)
        callback.set_killed(True, sender=admin)
        start, end = amm.read_user_tick_numbers(borrower)
        before = [callback.collateral_per_share(n) for n in range(start, end + 1)]
        frozen = callback.I_rpc()[0]

        soft_liquidate(amm, price_oracle, admin, trader, borrowed_token, 70)
        after = [callback.collateral_per_share(n) for n in range(start, end + 1)]
        assert after != before
        for n in range(start, end + 1):
            total_shares = amm.eval(f"self.total_shares[{n}]")
            assert (
                callback.collateral_per_share(n)
                == amm.bands_y(n) * 10**18 // total_shares
            )
        assert callback.I_rpc()[0] == frozen


@pytest.mark.parametrize("checkpoint", [False, True])
def test_crv_epoch_rollover_during_pause(
    admin, collateral_token, borrowed_token, controller, crv, lm_callback, checkpoint
):
    with boa.env.anchor():
        callback = lm_callback
        borrower = _borrower(
            collateral_token, borrowed_token, controller, crv, callback, admin
        )
        callback.set_killed(True, sender=admin)
        frozen = callback.I_rpc()[0]
        old_rate = crv.rate()
        boa.env.time_travel(seconds=365 * 86400 + WEEK)
        if checkpoint:
            callback.user_checkpoint(borrower)
            assert callback.inflation_rate() == crv.rate() < old_rate
            assert callback.I_rpc()[0] == frozen

        callback.set_killed(False, sender=admin)
        assert callback.inflation_rate() == crv.rate() < old_rate
        assert callback.I_rpc()[0] == frozen
        assert callback.I_rpc()[1] == boa.env.timestamp
        boa.env.time_travel(seconds=WEEK)
        callback.user_checkpoint(borrower)
        assert callback.integrate_fraction(borrower) > 0


@pytest.mark.parametrize("checkpoint", [False, True])
def test_disconnected_callback_cannot_resume(
    admin, controller, configurator, lm_callback, checkpoint
):
    with boa.env.anchor():
        callback = lm_callback
        callback.set_killed(True, sender=admin)
        configurator.set_callback(controller, ZERO_ADDRESS, sender=admin)
        if checkpoint:
            callback.user_checkpoint(ZERO_ADDRESS)
        with boa.reverts("not attached"):
            callback.set_killed(False, sender=admin)
        assert callback.is_killed()


def test_retirement_cannot_be_cleared_by_setter(
    admin, controller, configurator, lm_callback
):
    with boa.env.anchor():
        callback = lm_callback
        callback.set_killed(True, sender=admin)
        configurator.set_callback(controller, ZERO_ADDRESS, sender=admin)
        callback.user_checkpoint(ZERO_ADDRESS)
        assert callback.detached()
        configurator.set_callback(controller, callback, sender=admin)
        with boa.reverts("not attached"):
            callback.set_killed(False, sender=admin)
        assert callback.is_killed()
