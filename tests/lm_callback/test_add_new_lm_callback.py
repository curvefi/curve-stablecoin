import boa

WEEK = 7 * 86400


def test_add_new_lm_callback(
        accounts,
        admin,
        chad,
        collateral_token,
        crv,
        market_controller,
        market_amm,
        lm_callback,
        minter,
        gauge_controller,
        controller_factory
):
    alice, bob = accounts[:2]

    # Remove current LM Callback
    market_controller.set_callback("0x0000000000000000000000000000000000000000", sender=admin)

    boa.env.time_travel(seconds=2 * WEEK + 5)

    # Create loan
    collateral_token._mint_for_testing(alice, 10**22, sender=admin)
    market_controller.create_loan(10**21, 10**21 * 2600, 10, sender=alice)
    collateral_token._mint_for_testing(bob, 10**22, sender=admin)
    market_controller.create_loan(10**21, 10**21 * 2600, 10, sender=bob)

    # Wire up the new LM Callback to the gauge controller to have proper rates and stuff
    with boa.env.prank(admin):
        new_cb = boa.load('contracts/LMCallback.vy', market_amm, crv, gauge_controller, minter, controller_factory)
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
