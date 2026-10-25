import boa
import pytest

from tests.utils.constants import MAX_UINT256, ZERO_ADDRESS

WEEK = 7 * 86400


def test_is_not_killed_before_attachment(
    admin, amm, controller, configurator, deploy_lm_callback
):
    with boa.env.anchor():
        callback = deploy_lm_callback(amm)
        assert not callback.is_killed()
        assert not callback.attached()
        assert not callback.detached()

        callback.user_checkpoint(ZERO_ADDRESS)
        assert not callback.is_killed()
        assert not callback.attached()
        assert not callback.detached()

        configurator.set_callback(controller, callback, sender=admin)
        assert not callback.is_killed()
        # Reading the flag must not change the attachment bookkeeping.
        assert not callback.attached()


@pytest.mark.parametrize("checkpoint", [False, True])
def test_is_killed_while_attached(lm_callback, checkpoint):
    with boa.env.anchor():
        if checkpoint:
            lm_callback.user_checkpoint(ZERO_ADDRESS)
        assert not lm_callback.is_killed()


@pytest.mark.parametrize("replacement", [ZERO_ADDRESS, "other_callback"])
def test_is_killed_on_detach(admin, controller, configurator, lm_callback, replacement):
    with boa.env.anchor():
        lm_callback.user_checkpoint(ZERO_ADDRESS)
        if replacement == "other_callback":
            replacement = boa.env.generate_address("other_callback")
        configurator.set_callback(controller, replacement, sender=admin)

        assert lm_callback.is_killed()
        assert not lm_callback.detached()

        lm_callback.user_checkpoint(ZERO_ADDRESS)
        assert lm_callback.detached()
        assert lm_callback.is_killed()

        configurator.set_callback(controller, lm_callback, sender=admin)
        assert lm_callback.is_killed()


def test_is_not_killed_without_emissions(admin, lm_callback, gauge_controller):
    with boa.env.anchor():
        lm_callback.user_checkpoint(ZERO_ADDRESS)
        assert lm_callback.total_collateral() == 0
        assert not lm_callback.is_killed()

        gauge_controller.change_gauge_weight(lm_callback.address, 0, sender=admin)
        assert gauge_controller.get_gauge_weight(lm_callback.address) == 0
        assert not lm_callback.is_killed()


def test_is_killed_view_does_not_latch_retirement(
    admin, controller, configurator, lm_callback
):
    with boa.env.anchor():
        lm_callback.user_checkpoint(ZERO_ADDRESS)
        configurator.set_callback(controller, ZERO_ADDRESS, sender=admin)
        assert lm_callback.is_killed()
        assert not lm_callback.detached()

        # A view cannot remember a gap: retirement needs a disconnected checkpoint.
        configurator.set_callback(controller, lm_callback, sender=admin)
        assert not lm_callback.is_killed()


def test_killed_callback_can_mint_recorded_rewards(
    admin, collateral_token, controller, configurator, crv, lm_callback, minter
):
    with boa.env.anchor():
        borrower = boa.env.generate_address("borrower")
        boa.deal(collateral_token, borrower, 10**21)
        collateral_token.approve(controller, MAX_UINT256, sender=borrower)

        boa.env.time_travel(seconds=2 * WEEK + 5)
        crv.update_mining_parameters()
        lm_callback.user_checkpoint(ZERO_ADDRESS)
        controller.create_loan(10**21, 1500 * 10**21, 10, sender=borrower)
        boa.env.time_travel(seconds=WEEK)
        lm_callback.user_checkpoint(borrower)
        earned = lm_callback.integrate_fraction(borrower)
        assert earned > 0

        configurator.set_callback(controller, ZERO_ADDRESS, sender=admin)
        lm_callback.user_checkpoint(ZERO_ADDRESS)
        assert lm_callback.is_killed()

        minter.mint(lm_callback.address, sender=borrower)
        assert crv.balanceOf(borrower) == earned
        assert lm_callback.integrate_fraction(borrower) == earned
