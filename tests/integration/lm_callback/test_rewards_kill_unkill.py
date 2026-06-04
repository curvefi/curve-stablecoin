import boa
from tests.utils.constants import MAX_UINT256

WEEK = 7 * 86400


def test_rewards_kill(
    admin,
    collateral_token,
    crv,
    controller,
    lm_callback,
    minter,
):
    print("")
    borrower = boa.env.generate_address("borrower")
    boa.deal(collateral_token, borrower, 1000 * 10**18)
    collateral_token.approve(controller, MAX_UINT256, sender=borrower)

    boa.env.time_travel(seconds=2 * WEEK + 5)

    controller.create_loan(10**21, 10**21 * 2600, 10, sender=borrower)

    boa.env.time_travel(WEEK)
    lm_callback.user_checkpoint(borrower, sender=borrower)

    rewards0 = lm_callback.integrate_fraction(borrower)
    print(rewards0, " - Rewards BEFORE killing")

    with boa.env.anchor():
        boa.env.time_travel(WEEK)

        lm_callback.user_checkpoint(borrower, sender=borrower)

        rewards_ref = lm_callback.integrate_fraction(borrower)
        print(rewards_ref, "- Rewards WITHOUT killing")

    with boa.env.anchor():
        boa.env.time_travel(WEEK)

        with boa.env.prank(admin):
            lm_callback.set_killed(True)

        lm_callback.user_checkpoint(borrower, sender=borrower)

        rewards1 = lm_callback.integrate_fraction(borrower)
        print(rewards1, "- Rewards WITH killing")

    assert rewards1 == rewards_ref == 2 * rewards0


def test_rewards_kill_unkill(
    admin,
    collateral_token,
    crv,
    controller,
    lm_callback,
    minter,
):
    print("")
    borrower = boa.env.generate_address("borrower")
    boa.deal(collateral_token, borrower, 1000 * 10**18)
    collateral_token.approve(controller, MAX_UINT256, sender=borrower)

    boa.env.time_travel(seconds=2 * WEEK + 5)

    controller.create_loan(10**21, 10**21 * 2600, 10, sender=borrower)

    boa.env.time_travel(WEEK)
    lm_callback.user_checkpoint(borrower, sender=borrower)

    rewards0 = lm_callback.integrate_fraction(borrower)
    print(rewards0, " - Rewards BEFORE killing")

    with boa.env.anchor():
        boa.env.time_travel(2 * WEEK)

        lm_callback.user_checkpoint(borrower, sender=borrower)

        rewards_ref = lm_callback.integrate_fraction(borrower)
        print(rewards_ref, "- Rewards WITHOUT kill-unkill")

    with boa.env.anchor():
        boa.env.time_travel(WEEK)
        lm_callback.user_checkpoint(borrower, sender=borrower)

        with boa.env.prank(admin):
            lm_callback.set_killed(True)

        boa.env.time_travel(WEEK)
        lm_callback.user_checkpoint(borrower, sender=borrower)

        with boa.env.prank(admin):
            lm_callback.set_killed(False)

        lm_callback.user_checkpoint(borrower, sender=borrower)

        rewards1 = lm_callback.integrate_fraction(borrower)
        print(
            rewards1,
            "- Rewards WITH user_checkpoint call before killing and WITH gauge calls between kill-unkill",
        )

    with boa.env.anchor():
        boa.env.time_travel(WEEK)
        lm_callback.user_checkpoint(borrower, sender=borrower)

        with boa.env.prank(admin):
            lm_callback.set_killed(True)

        boa.env.time_travel(WEEK)
        # lm_callback.user_checkpoint(borrower, sender=borrower)

        with boa.env.prank(admin):
            lm_callback.set_killed(False)

        lm_callback.user_checkpoint(borrower, sender=borrower)

        rewards2 = lm_callback.integrate_fraction(borrower)
        print(
            rewards2,
            "- Rewards WITH user_checkpoint call before killing and WITHOUT gauge calls between kill-unkill",
        )

    with boa.env.anchor():
        boa.env.time_travel(WEEK)
        # lm_callback.user_checkpoint(borrower, sender=borrower)

        with boa.env.prank(admin):
            lm_callback.set_killed(True)

        boa.env.time_travel(WEEK)
        lm_callback.user_checkpoint(borrower, sender=borrower)

        with boa.env.prank(admin):
            lm_callback.set_killed(False)

        lm_callback.user_checkpoint(borrower, sender=borrower)

        rewards3 = lm_callback.integrate_fraction(borrower)
        print(
            rewards3,
            "- Rewards WITHOUT user_checkpoint call before killing and WITH gauge calls between kill-unkill",
        )

    with boa.env.anchor():
        boa.env.time_travel(WEEK)
        # lm_callback.user_checkpoint(borrower, sender=borrower)

        with boa.env.prank(admin):
            lm_callback.set_killed(True)

        boa.env.time_travel(WEEK)
        # lm_callback.user_checkpoint(borrower, sender=borrower)

        with boa.env.prank(admin):
            lm_callback.set_killed(False)

        lm_callback.user_checkpoint(borrower, sender=borrower)

        rewards4 = lm_callback.integrate_fraction(borrower)
        print(
            rewards4,
            "- Rewards WITHOUT user_checkpoint call before killing and WITHOUT gauge calls between kill-unkill",
        )

    # Checkpoints cause little inaccuracy
    assert (
        rewards1
        == rewards2
        == rewards3
        == rewards4 - 10**6
        == rewards_ref - 10**6
        == 3 * rewards0
    )
