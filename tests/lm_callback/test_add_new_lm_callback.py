import boa
from tests.utils.deployers import LM_CALLBACK_DEPLOYER
from tests.utils.constants import ZERO_ADDRESS

WEEK = 7 * 86400


def test_add_new_lm_callback(
        accounts,
        admin,
        collateral_token,
        crv,
        market_controller,
        market_amm,
        minter,
        gauge_controller,
        controller_factory
):
    alice, bob = accounts[:2]

    # Remove current LM Callback
    market_controller.set_callback(ZERO_ADDRESS, sender=admin)

    boa.env.time_travel(seconds=2 * WEEK + 5)

    # Create loan
    boa.deal(collateral_token, alice, 10**22)
    market_controller.create_loan(10**21, 10**21 * 2600, 10, sender=alice)
    boa.deal(collateral_token, bob, 10**22)
    market_controller.create_loan(10**21, 10**21 * 2600, 10, sender=bob)

    # Wire up the new LM Callback to the gauge controller to have proper rates and stuff
    with boa.env.prank(admin):
        new_cb = LM_CALLBACK_DEPLOYER.deploy(market_amm, crv, gauge_controller, minter, controller_factory)
        market_controller.set_callback(new_cb)
        gauge_controller.add_gauge(new_cb.address, 0, 10 ** 18)

    boa.env.time_travel(WEEK)
    new_cb.user_checkpoint(alice, sender=alice)

    # Alice does not receive rewards
    rewards = new_cb.integrate_fraction(alice)
    collateral_from_amm = market_controller.user_state(alice)[0]
    collateral_from_cb = new_cb.user_collateral(alice)

    assert collateral_from_cb == collateral_from_amm == 10**21
    assert rewards == 0

    # Bob interacts with the market
    market_controller.borrow_more(0, 10 ** 18, sender=bob)

    boa.env.time_travel(WEEK)
    new_cb.user_checkpoint(alice, sender=alice)

    # Now Alice receives rewards
    rewards = new_cb.integrate_fraction(alice)
    collateral_from_amm = market_controller.user_state(alice)[0]
    collateral_from_cb = new_cb.user_collateral(alice)

    assert collateral_from_cb == collateral_from_amm == 10 ** 21
    assert rewards > 0
