import boa
from random import random, randrange
import pytest
from tests.utils.constants import MAX_UINT256
YEAR = 365 * 86400
WEEK = 7 * 86400


def test_gauge_integral_one_user(
    admin, collateral_token, borrowed_token, crv, lm_callback, controller, minter
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
        checkpoint_supply = 0
        checkpoint_balance = 0

        def update_integral():
            nonlocal \
                checkpoint, \
                checkpoint_rate, \
                integral, \
                checkpoint_balance, \
                checkpoint_supply

            t1 = boa.env.timestamp
            rate1 = crv.rate()
            t_epoch = crv.start_epoch_time_write(sender=admin)
            if checkpoint >= t_epoch:
                rate_x_time = (t1 - checkpoint) * rate1
            else:
                rate_x_time = (t_epoch - checkpoint) * checkpoint_rate + (
                    t1 - t_epoch
                ) * rate1
            if checkpoint_supply > 0:
                integral += rate_x_time * checkpoint_balance // checkpoint_supply
            checkpoint_rate = rate1
            checkpoint = t1
            checkpoint_supply = lm_callback.total_collateral()
            checkpoint_balance = lm_callback.user_collateral(borrower)

        for i in range(40):
            dt = 3 * (i + 1) * 86400
            boa.env.time_travel(seconds=dt)

            is_withdraw = (i > 0) * (random() < 0.5)
            with boa.env.prank(borrower):
                collateral_in_amm, _, debt, __ = controller.user_state(borrower)
                collateral_borrower = lm_callback.user_collateral(borrower)
                assert collateral_in_amm == collateral_borrower
                print("borrower", "withdraws" if is_withdraw else "deposits")

                if is_withdraw:
                    amount = randrange(1, collateral_in_amm + 1)
                    if amount == collateral_in_amm:
                        controller.repay(debt)
                    else:
                        repay_amount = int(debt * random() * 0.99)
                        controller.repay(repay_amount)
                        min_collateral_required = controller.min_collateral(
                            debt - repay_amount, 10
                        )
                        remove_amount = min(
                            collateral_in_amm - min_collateral_required, amount
                        )
                        remove_amount = max(remove_amount, 0)
                        if remove_amount > 0:
                            controller.remove_collateral(remove_amount)
                    update_integral()
                    borrower_staked -= remove_amount
                else:
                    amount = collateral_token.balanceOf(borrower) // 5
                    if controller.loan_exists(borrower):
                        controller.borrow_more(amount, int(amount * random() * 2000))
                    else:
                        controller.create_loan(
                            amount, int(amount * random() * 2000), 10
                        )
                    update_integral()
                    borrower_staked += amount

            assert lm_callback.user_collateral(borrower) == borrower_staked
            assert lm_callback.total_collateral() == borrower_staked

            dt = (i + 1) * 10 * 86400
            boa.env.time_travel(seconds=dt)

            lm_callback.user_checkpoint(borrower, sender=borrower)
            update_integral()
            print(i, dt / 86400, integral, lm_callback.integrate_fraction(borrower))
            crv_reward = lm_callback.integrate_fraction(borrower)
            assert crv_reward == pytest.approx(integral, rel=1e-14)
            minter.mint(lm_callback.address, sender=borrower)
            assert crv.balanceOf(borrower) == crv_reward


def test_gauge_integral(
    admin, collateral_token, borrowed_token, crv, lm_callback, controller, minter
):
    with boa.env.anchor():
        borrower1 = boa.env.generate_address("borrower1")
        borrower2 = boa.env.generate_address("borrower2")
        for b in (borrower1, borrower2):
            boa.deal(collateral_token, b, 1000 * 10 ** 18)
            collateral_token.approve(controller, MAX_UINT256, sender=b)
            borrowed_token.approve(controller, MAX_UINT256, sender=b)

        borrower1_staked = 0
        borrower2_staked = 0
        integral = 0  # ∫(balance * rate(t) / totalSupply(t) dt)
        checkpoint = boa.env.timestamp
        boa.env.time_travel(blocks=1)
        checkpoint_rate = crv.rate()
        checkpoint_supply = 0
        checkpoint_balance = 0

        def update_integral():
            nonlocal \
                checkpoint, \
                checkpoint_rate, \
                integral, \
                checkpoint_balance, \
                checkpoint_supply

            t1 = boa.env.timestamp
            rate1 = crv.rate()
            t_epoch = crv.start_epoch_time()
            if checkpoint >= t_epoch:
                rate_x_time = (t1 - checkpoint) * rate1
            else:
                rate_x_time = (t_epoch - checkpoint) * checkpoint_rate + (
                    t1 - t_epoch
                ) * rate1
            if checkpoint_supply > 0:
                integral += rate_x_time * checkpoint_balance // checkpoint_supply
            checkpoint_rate = rate1
            checkpoint = t1
            checkpoint_supply = lm_callback.total_collateral()
            checkpoint_balance = lm_callback.user_collateral(borrower1)

        # borrower2 always deposits or withdraws; borrower1 does so more rarely
        for i in range(40):
            is_borrower1 = random() < 0.2
            dt = randrange(1, YEAR // 5)
            boa.env.time_travel(seconds=dt)

            with boa.env.prank(borrower2):
                is_withdraw_borrower2 = (i > 0) * (random() < 0.5)
                print("borrower2", "withdraws" if is_withdraw_borrower2 else "deposits")
                if is_withdraw_borrower2:
                    collateral_in_amm_borrower2, _, debt_borrower2, __ = controller.user_state(borrower2)
                    collateral_borrower2 = lm_callback.user_collateral(borrower2)
                    assert collateral_in_amm_borrower2 == collateral_borrower2
                    amount_borrower2 = randrange(1, collateral_in_amm_borrower2 + 1)
                    remove_amount_borrower2 = amount_borrower2
                    if amount_borrower2 == collateral_in_amm_borrower2:
                        controller.repay(debt_borrower2)
                    else:
                        repay_amount_borrower2 = int(debt_borrower2 * random() * 0.99)
                        controller.repay(repay_amount_borrower2)
                        min_collateral_required_borrower2 = controller.min_collateral(
                            debt_borrower2 - repay_amount_borrower2, 10
                        )
                        remove_amount_borrower2 = min(
                            collateral_in_amm_borrower2 - min_collateral_required_borrower2,
                            amount_borrower2,
                        )
                        remove_amount_borrower2 = max(remove_amount_borrower2, 0)
                        if remove_amount_borrower2 > 0:
                            controller.remove_collateral(remove_amount_borrower2)
                    update_integral()
                    borrower2_staked -= remove_amount_borrower2
                else:
                    amount_borrower2 = randrange(1, collateral_token.balanceOf(borrower2) // 10 + 1)
                    if controller.loan_exists(borrower2):
                        controller.borrow_more(
                            amount_borrower2, int(amount_borrower2 * random() * 2000)
                        )
                    else:
                        controller.create_loan(
                            amount_borrower2, int(amount_borrower2 * random() * 2000), 10
                        )
                    update_integral()
                    borrower2_staked += amount_borrower2

            if is_borrower1:
                with boa.env.prank(borrower1):
                    collateral_in_amm_borrower1, _, debt_borrower1, __ = controller.user_state(
                        borrower1
                    )
                    collateral_borrower1 = lm_callback.user_collateral(borrower1)
                    assert collateral_in_amm_borrower1 == collateral_borrower1
                    is_withdraw_borrower1 = (collateral_in_amm_borrower1 > 0) * (random() < 0.5)
                    print("borrower1", "withdraws" if is_withdraw_borrower1 else "deposits")

                    if is_withdraw_borrower1:
                        amount_borrower1 = randrange(1, collateral_in_amm_borrower1 + 1)
                        remove_amount_borrower1 = amount_borrower1
                        if amount_borrower1 == collateral_in_amm_borrower1:
                            controller.repay(debt_borrower1)
                        else:
                            repay_amount_borrower1 = int(debt_borrower1 * random() * 0.99)
                            controller.repay(repay_amount_borrower1)
                            min_collateral_required_borrower1 = controller.min_collateral(
                                debt_borrower1 - repay_amount_borrower1, 10
                            )
                            remove_amount_borrower1 = min(
                                collateral_in_amm_borrower1 - min_collateral_required_borrower1,
                                amount_borrower1,
                            )
                            remove_amount_borrower1 = max(remove_amount_borrower1, 0)
                            if remove_amount_borrower1 > 0:
                                controller.remove_collateral(remove_amount_borrower1)
                        update_integral()
                        borrower1_staked -= remove_amount_borrower1
                    else:
                        amount_borrower1 = randrange(
                            1, collateral_token.balanceOf(borrower1) // 10 + 1
                        )
                        if controller.loan_exists(borrower1):
                            controller.borrow_more(
                                amount_borrower1, int(amount_borrower1 * random() * 2000)
                            )
                        else:
                            controller.create_loan(
                                amount_borrower1, int(amount_borrower1 * random() * 2000), 10
                            )
                        update_integral()
                        borrower1_staked += amount_borrower1

            # Checking that updating the checkpoint in the same second does nothing
            # Also everyone can update: that should make no difference, too
            if random() < 0.5:
                lm_callback.user_checkpoint(borrower1, sender=borrower1)
            if random() < 0.5:
                lm_callback.user_checkpoint(borrower2, sender=borrower2)

            assert lm_callback.user_collateral(borrower1) == borrower1_staked
            assert lm_callback.user_collateral(borrower2) == borrower2_staked
            assert lm_callback.total_collateral() == borrower1_staked + borrower2_staked

            dt = randrange(1, YEAR // 20)
            boa.env.time_travel(seconds=dt)

            with boa.env.prank(borrower1):
                crv_balance = crv.balanceOf(borrower1)
                with boa.env.anchor():
                    crv_reward = lm_callback.claimable_tokens(borrower1)
                minter.mint(lm_callback.address)
                assert crv.balanceOf(borrower1) - crv_balance == crv_reward

                update_integral()
                print(i, dt / 86400, integral, lm_callback.integrate_fraction(borrower1))
                assert lm_callback.integrate_fraction(borrower1) == pytest.approx(
                    integral, rel=1e-14
                )

            with boa.env.prank(borrower2):
                crv_balance = crv.balanceOf(borrower2)
                with boa.env.anchor():
                    crv_reward = lm_callback.claimable_tokens(borrower2)
                minter.mint(lm_callback.address)
                assert crv.balanceOf(borrower2) - crv_balance == crv_reward


def test_set_killed(
    admin,
    collateral_token,
    crv,
    controller,
    lm_callback,
    minter,
):
    borrower = boa.env.generate_address("borrower")
    boa.deal(collateral_token, borrower, 1000 * 10**18)
    collateral_token.approve(controller, MAX_UINT256, sender=borrower)

    boa.env.time_travel(seconds=2 * WEEK + 5)

    controller.create_loan(10**21, 10**21 * 2600, 10, sender=borrower)

    boa.env.time_travel(4 * WEEK)

    with boa.env.anchor():
        rewards_borrower = lm_callback.claimable_tokens(borrower)
    assert rewards_borrower > 0
    crv_balance = crv.balanceOf(borrower)
    minter.mint(lm_callback.address, sender=borrower)
    assert crv.balanceOf(borrower) - crv_balance == rewards_borrower

    # Kill lm callback
    with boa.reverts("only owner"):
        lm_callback.set_killed(True, sender=borrower)
    lm_callback.set_killed(True, sender=admin)

    boa.env.time_travel(4 * WEEK)

    # No rewards while killed
    with boa.env.anchor():
        rewards_borrower = lm_callback.claimable_tokens(borrower)
    assert rewards_borrower == 0
    crv_balance = crv.balanceOf(borrower)
    minter.mint(lm_callback.address, sender=borrower)
    assert crv.balanceOf(borrower) == crv_balance

    # Unkill lm callback
    with boa.reverts("only owner"):
        lm_callback.set_killed(False, sender=borrower)
    lm_callback.set_killed(False, sender=admin)

    boa.env.time_travel(4 * WEEK)

    # Rewards resume after unkill
    with boa.env.anchor():
        rewards_borrower = lm_callback.claimable_tokens(borrower)
    assert rewards_borrower > 0
    crv_balance = crv.balanceOf(borrower)
    minter.mint(lm_callback.address, sender=borrower)
    assert crv.balanceOf(borrower) - crv_balance == rewards_borrower
