import boa
from tests.utils.deployers import LM_CALLBACK_DEPLOYER
from tests.utils.constants import MAX_UINT256, ZERO_ADDRESS

WEEK = 7 * 86400


def test_add_new_lm_callback(
    admin,
    collateral_token,
    crv,
    controller,
    amm,
    minter,
    gauge_controller,
    lm_factory,
):
    borrower1 = boa.env.generate_address("borrower1")
    borrower2 = boa.env.generate_address("borrower2")
    for b in (borrower1, borrower2):
        collateral_token.approve(controller, MAX_UINT256, sender=b)

    # Remove current LM Callback
    controller.set_callback(ZERO_ADDRESS, sender=admin)

    boa.env.time_travel(seconds=2 * WEEK + 5)

    # Create loan
    boa.deal(collateral_token, borrower1, 10**21)
    controller.create_loan(10**21, 10**21 * 2600, 10, sender=borrower1)
    boa.deal(collateral_token, borrower2, 10**21)
    controller.create_loan(10**21, 10**21 * 2600, 10, sender=borrower2)

    # Wire up the new LM Callback to the gauge controller to have proper rates and stuff
    with boa.env.prank(admin):
        new_cb = LM_CALLBACK_DEPLOYER.deploy(
            amm, crv, gauge_controller, minter, lm_factory
        )
        controller.set_callback(new_cb)
        gauge_controller.add_gauge(new_cb.address, 0, 10**18)

    boa.env.time_travel(WEEK)
    new_cb.user_checkpoint(borrower1, sender=borrower1)

    # borrower1 does not receive rewards
    rewards = new_cb.integrate_fraction(borrower1)
    collateral_from_amm = controller.user_state(borrower1)[0]
    collateral_from_cb = new_cb.user_collateral(borrower1)

    assert collateral_from_cb == collateral_from_amm == 10**21
    assert rewards == 0

    # borrower2 interacts with the market
    controller.borrow_more(0, 10**18, sender=borrower2)

    boa.env.time_travel(WEEK)
    new_cb.user_checkpoint(borrower1, sender=borrower1)

    # Now borrower1 receives rewards
    rewards = new_cb.integrate_fraction(borrower1)
    collateral_from_amm = controller.user_state(borrower1)[0]
    collateral_from_cb = new_cb.user_collateral(borrower1)

    assert collateral_from_cb == collateral_from_amm == 10**21
    assert rewards > 0
