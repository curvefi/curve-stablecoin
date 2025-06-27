import boa

WEEK = 7 * 86400


def test_rewards_kill(
        accounts,
        admin,
        chad,
        collateral_token,
        crv,
        market_controller,
        market_amm,
        lm_callback,
        minter,
):
    print("")
    alice = accounts[0]

    boa.env.time_travel(seconds=2 * WEEK + 5)

    with boa.env.prank(admin):
        collateral_token._mint_for_testing(alice, 1000 * 10 ** 18)

    market_controller.create_loan(10**21, 10**21 * 2600, 10, sender=alice)

    boa.env.time_travel(WEEK)
    lm_callback.user_checkpoint(alice, sender=alice)

    rewards0 = lm_callback.integrate_fraction(alice)
    print(rewards0, " - Rewards BEFORE killing")

    with boa.env.anchor():
        boa.env.time_travel(WEEK)

        lm_callback.user_checkpoint(alice, sender=alice)

        rewards_ref = lm_callback.integrate_fraction(alice)
        print(rewards_ref, "- Rewards WITHOUT killing")

    with boa.env.anchor():
        boa.env.time_travel(WEEK)

        with boa.env.prank(admin):
            lm_callback.set_killed(True)

        lm_callback.user_checkpoint(alice, sender=alice)

        rewards1 = lm_callback.integrate_fraction(alice)
        print(rewards1, "- Rewards WITH killing")

    assert rewards1 == rewards_ref == 2 * rewards0


def test_rewards_kill_unkill(
        accounts,
        admin,
        chad,
        collateral_token,
        crv,
        market_controller,
        market_amm,
        lm_callback,
        minter,
):
    print("")
    alice = accounts[0]

    boa.env.time_travel(seconds=2 * WEEK + 5)

    with boa.env.prank(admin):
        collateral_token._mint_for_testing(alice, 1000 * 10 ** 18)

    market_controller.create_loan(10**21, 10**21 * 2600, 10, sender=alice)

    boa.env.time_travel(WEEK)
    lm_callback.user_checkpoint(alice, sender=alice)

    rewards0 = lm_callback.integrate_fraction(alice)
    print(rewards0, " - Rewards BEFORE killing")

    with boa.env.anchor():
        boa.env.time_travel(2 * WEEK)

        lm_callback.user_checkpoint(alice, sender=alice)

        rewards_ref = lm_callback.integrate_fraction(alice)
        print(rewards_ref, "- Rewards WITHOUT kill-unkill")

    with boa.env.anchor():
        boa.env.time_travel(WEEK)
        lm_callback.user_checkpoint(alice, sender=alice)

        with boa.env.prank(admin):
            lm_callback.set_killed(True)

        boa.env.time_travel(WEEK)
        lm_callback.user_checkpoint(alice, sender=alice)

        with boa.env.prank(admin):
            lm_callback.set_killed(False)

        lm_callback.user_checkpoint(alice, sender=alice)

        rewards1 = lm_callback.integrate_fraction(alice)
        print(rewards1, "- Rewards WITH user_checkpoint call before killing and WITH gauge calls between kill-unkill")

    with boa.env.anchor():
        boa.env.time_travel(WEEK)
        lm_callback.user_checkpoint(alice, sender=alice)

        with boa.env.prank(admin):
            lm_callback.set_killed(True)

        boa.env.time_travel(WEEK)
        # lm_callback.user_checkpoint(alice, sender=alice)

        with boa.env.prank(admin):
            lm_callback.set_killed(False)

        lm_callback.user_checkpoint(alice, sender=alice)

        rewards2 = lm_callback.integrate_fraction(alice)
        print(rewards2, "- Rewards WITH user_checkpoint call before killing and WITHOUT gauge calls between kill-unkill")

    with boa.env.anchor():
        boa.env.time_travel(WEEK)
        #lm_callback.user_checkpoint(alice, sender=alice)

        with boa.env.prank(admin):
            lm_callback.set_killed(True)

        boa.env.time_travel(WEEK)
        lm_callback.user_checkpoint(alice, sender=alice)

        with boa.env.prank(admin):
            lm_callback.set_killed(False)

        lm_callback.user_checkpoint(alice, sender=alice)

        rewards3 = lm_callback.integrate_fraction(alice)
        print(rewards3, "- Rewards WITHOUT user_checkpoint call before killing and WITH gauge calls between kill-unkill")

    with boa.env.anchor():
        boa.env.time_travel(WEEK)
        # lm_callback.user_checkpoint(alice, sender=alice)

        with boa.env.prank(admin):
            lm_callback.set_killed(True)

        boa.env.time_travel(WEEK)
        # lm_callback.user_checkpoint(alice, sender=alice)

        with boa.env.prank(admin):
            lm_callback.set_killed(False)

        lm_callback.user_checkpoint(alice, sender=alice)

        rewards4 = lm_callback.integrate_fraction(alice)
        print(rewards4, "- Rewards WITHOUT user_checkpoint call before killing and WITHOUT gauge calls between kill-unkill")

    # Checkpoints cause little inaccuracy
    assert rewards1 == rewards2 == rewards3 == rewards4 - 10**6 == rewards_ref - 10**6 == 3 * rewards0
