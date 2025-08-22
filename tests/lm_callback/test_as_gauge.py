import boa
from random import random, randrange
import pytest

MAX_UINT256 = 2 ** 256 - 1
YEAR = 365 * 86400
WEEK = 7 * 86400


def test_gauge_integral_one_user(accounts, admin, collateral_token, crv, lm_callback, market_controller, minter):
    with boa.env.anchor():
        alice = accounts[0]
        boa.env.time_travel(seconds=WEEK)
        alice_staked = 0
        integral = 0  # ∫(balance * rate(t) / totalSupply(t) dt)
        checkpoint = boa.env.evm.patch.timestamp
        checkpoint_rate = crv.rate()
        checkpoint_supply = 0
        checkpoint_balance = 0

        boa.deal(collateral_token, alice, 1000 * 10**18)

        def update_integral():
            nonlocal checkpoint, checkpoint_rate, integral, checkpoint_balance, checkpoint_supply

            t1 = boa.env.evm.patch.timestamp
            rate1 = crv.rate()
            t_epoch = crv.start_epoch_time_write(sender=admin)
            if checkpoint >= t_epoch:
                rate_x_time = (t1 - checkpoint) * rate1
            else:
                rate_x_time = (t_epoch - checkpoint) * checkpoint_rate + (t1 - t_epoch) * rate1
            if checkpoint_supply > 0:
                integral += rate_x_time * checkpoint_balance // checkpoint_supply
            checkpoint_rate = rate1
            checkpoint = t1
            checkpoint_supply = lm_callback.total_collateral()
            checkpoint_balance = lm_callback.user_collateral(alice)

        for i in range(40):
            dt = 3 * (i + 1) * 86400
            boa.env.time_travel(seconds=dt)

            is_withdraw = (i > 0) * (random() < 0.5)
            with boa.env.prank(alice):
                collateral_in_amm, _, debt, __ = market_controller.user_state(alice)
                collateral_alice = lm_callback.user_collateral(alice)
                assert collateral_in_amm == collateral_alice
                print("Alice", "withdraws" if is_withdraw else "deposits")

                if is_withdraw:
                    amount = randrange(1, collateral_in_amm + 1)
                    if amount == collateral_in_amm:
                        market_controller.repay(debt)
                    else:
                        repay_amount = int(debt * random() * 0.99)
                        market_controller.repay(repay_amount)
                        min_collateral_required = market_controller.min_collateral(debt - repay_amount, 10)
                        remove_amount = min(collateral_in_amm - min_collateral_required, amount)
                        remove_amount = max(remove_amount, 0)
                        if remove_amount > 0:
                            market_controller.remove_collateral(remove_amount)
                    update_integral()
                    alice_staked -= remove_amount
                else:
                    amount = collateral_token.balanceOf(alice) // 5
                    collateral_token.approve(market_controller.address, amount)
                    if market_controller.loan_exists(alice):
                        market_controller.borrow_more(amount, int(amount * random() * 2000))
                    else:
                        market_controller.create_loan(amount, int(amount * random() * 2000), 10)
                    update_integral()
                    alice_staked += amount

            assert lm_callback.user_collateral(alice) == alice_staked
            assert lm_callback.total_collateral() == alice_staked

            dt = (i + 1) * 10 * 86400
            boa.env.time_travel(seconds=dt)

            lm_callback.user_checkpoint(alice, sender=alice)
            update_integral()
            print(i, dt / 86400, integral, lm_callback.integrate_fraction(alice))
            crv_reward = lm_callback.integrate_fraction(alice)
            assert crv_reward == pytest.approx(integral, rel=1e-14)
            minter.mint(lm_callback.address, sender=alice)
            assert crv.balanceOf(alice) == crv_reward


def test_gauge_integral(accounts, admin, collateral_token, crv, lm_callback, market_controller, minter):
    with boa.env.anchor():
        alice, bob = accounts[:2]

        alice_staked = 0
        bob_staked = 0
        integral = 0  # ∫(balance * rate(t) / totalSupply(t) dt)
        checkpoint = boa.env.evm.patch.timestamp
        boa.env.time_travel(blocks=1)
        checkpoint_rate = crv.rate()
        checkpoint_supply = 0
        checkpoint_balance = 0

        # Let Alice and Bob have about the same collateral token amount
        with boa.env.prank(admin):
            boa.deal(collateral_token, alice, 1000 * 10**18)
            boa.deal(collateral_token, bob, 1000 * 10**18)

        def update_integral():
            nonlocal checkpoint, checkpoint_rate, integral, checkpoint_balance, checkpoint_supply

            t1 = boa.env.evm.patch.timestamp
            rate1 = crv.rate()
            t_epoch = crv.start_epoch_time()
            if checkpoint >= t_epoch:
                rate_x_time = (t1 - checkpoint) * rate1
            else:
                rate_x_time = (t_epoch - checkpoint) * checkpoint_rate + (t1 - t_epoch) * rate1
            if checkpoint_supply > 0:
                integral += rate_x_time * checkpoint_balance // checkpoint_supply
            checkpoint_rate = rate1
            checkpoint = t1
            checkpoint_supply = lm_callback.total_collateral()
            checkpoint_balance = lm_callback.user_collateral(alice)

        # Now let's have a loop where Bob always deposit or withdraws,
        # and Alice does so more rarely
        for i in range(40):
            is_alice = random() < 0.2
            dt = randrange(1, YEAR // 5)
            boa.env.time_travel(seconds=dt)

            # For Bob
            with boa.env.prank(bob):
                is_withdraw_bob = (i > 0) * (random() < 0.5)
                print("Bob", "withdraws" if is_withdraw_bob else "deposits")
                if is_withdraw_bob:
                    collateral_in_amm_bob, _, debt_bob, __ = market_controller.user_state(bob)
                    collateral_bob = lm_callback.user_collateral(bob)
                    assert collateral_in_amm_bob == collateral_bob
                    amount_bob = randrange(1, collateral_in_amm_bob + 1)
                    remove_amount_bob = amount_bob
                    if amount_bob == collateral_in_amm_bob:
                        market_controller.repay(debt_bob)
                    else:
                        repay_amount_bob = int(debt_bob * random() * 0.99)
                        market_controller.repay(repay_amount_bob)
                        min_collateral_required_bob = market_controller.min_collateral(debt_bob - repay_amount_bob, 10)
                        remove_amount_bob = min(collateral_in_amm_bob - min_collateral_required_bob, amount_bob)
                        remove_amount_bob = max(remove_amount_bob, 0)
                        if remove_amount_bob > 0:
                            market_controller.remove_collateral(remove_amount_bob)
                    update_integral()
                    bob_staked -= remove_amount_bob
                else:
                    amount_bob = randrange(1, collateral_token.balanceOf(bob) // 10 + 1)
                    collateral_token.approve(market_controller.address, amount_bob)
                    if market_controller.loan_exists(bob):
                        market_controller.borrow_more(amount_bob, int(amount_bob * random() * 2000))
                    else:
                        market_controller.create_loan(amount_bob, int(amount_bob * random() * 2000), 10)
                    update_integral()
                    bob_staked += amount_bob

            if is_alice:
                # For Alice
                with boa.env.prank(alice):
                    collateral_in_amm_alice, _, debt_alice, __ = market_controller.user_state(alice)
                    collateral_alice = lm_callback.user_collateral(alice)
                    assert collateral_in_amm_alice == collateral_alice
                    is_withdraw_alice = (collateral_in_amm_alice > 0) * (random() < 0.5)
                    print("Alice", "withdraws" if is_withdraw_alice else "deposits")

                    if is_withdraw_alice:
                        amount_alice = randrange(1, collateral_in_amm_alice + 1)
                        remove_amount_alice = amount_alice
                        if amount_alice == collateral_in_amm_alice:
                            market_controller.repay(debt_alice)
                        else:
                            repay_amount_alice = int(debt_alice * random() * 0.99)
                            market_controller.repay(repay_amount_alice)
                            min_collateral_required_alice = market_controller.min_collateral(debt_alice - repay_amount_alice, 10)
                            remove_amount_alice = min(collateral_in_amm_alice - min_collateral_required_alice, amount_alice)
                            remove_amount_alice = max(remove_amount_alice, 0)
                            if remove_amount_alice > 0:
                                market_controller.remove_collateral(remove_amount_alice)
                        update_integral()
                        alice_staked -= remove_amount_alice
                    else:
                        amount_alice = randrange(1, collateral_token.balanceOf(alice) // 10 + 1)
                        collateral_token.approve(market_controller.address, amount_alice)
                        if market_controller.loan_exists(alice):
                            market_controller.borrow_more(amount_alice, int(amount_alice * random() * 2000))
                        else:
                            market_controller.create_loan(amount_alice, int(amount_alice * random() * 2000), 10)
                        update_integral()
                        alice_staked += amount_alice

            # Checking that updating the checkpoint in the same second does nothing
            # Also everyone can update: that should make no difference, too
            if random() < 0.5:
                lm_callback.user_checkpoint(alice, sender=alice)
            if random() < 0.5:
                lm_callback.user_checkpoint(bob, sender=bob)

            assert lm_callback.user_collateral(alice) == alice_staked
            assert lm_callback.user_collateral(bob) == bob_staked
            assert lm_callback.total_collateral() == alice_staked + bob_staked

            dt = randrange(1, YEAR // 20)
            boa.env.time_travel(seconds=dt)

            with boa.env.prank(alice):
                crv_balance = crv.balanceOf(alice)
                with boa.env.anchor():
                    crv_reward = lm_callback.claimable_tokens(alice)
                minter.mint(lm_callback.address)
                assert crv.balanceOf(alice) - crv_balance == crv_reward

                update_integral()
                print(i, dt / 86400, integral, lm_callback.integrate_fraction(alice))
                assert lm_callback.integrate_fraction(alice) == pytest.approx(integral, rel=1e-14)

            with boa.env.prank(bob):
                crv_balance = crv.balanceOf(bob)
                with boa.env.anchor():
                    crv_reward = lm_callback.claimable_tokens(bob)
                minter.mint(lm_callback.address)
                assert crv.balanceOf(bob) - crv_balance == crv_reward


def test_set_killed(
        accounts,
        admin,
        collateral_token,
        crv,
        market_controller,
        lm_callback,
        minter,
):
    alice = accounts[0]
    boa.env.time_travel(seconds=2 * WEEK + 5)

    with boa.env.prank(admin):
        boa.deal(collateral_token, alice, 1000 * 10 ** 18)

    # Alice creates loan
    market_controller.create_loan(10**21, 10**21 * 2600, 10, sender=alice)

    # Time travel and checkpoint
    boa.env.time_travel(4 * WEEK)

    # Alice got some rewards
    with boa.env.anchor():
        rewards_alice = lm_callback.claimable_tokens(alice)
    assert rewards_alice > 0
    crv_balance = crv.balanceOf(alice)
    minter.mint(lm_callback.address, sender=alice)
    assert crv.balanceOf(alice) - crv_balance == rewards_alice

    # Kill lm callback
    with boa.reverts('only owner'):
        lm_callback.set_killed(True, sender=alice)
    lm_callback.set_killed(True, sender=admin)

    # Time travel and checkpoint
    boa.env.time_travel(4 * WEEK)

    # Alice didn't get any rewards since lm callback is killed
    with boa.env.anchor():
        rewards_alice = lm_callback.claimable_tokens(alice)
    assert rewards_alice == 0
    crv_balance = crv.balanceOf(alice)
    minter.mint(lm_callback.address, sender=alice)
    assert crv.balanceOf(alice) == crv_balance

    # Unkill lm callback
    with boa.reverts('only owner'):
        lm_callback.set_killed(False, sender=alice)
    lm_callback.set_killed(False, sender=admin)

    # Time travel and checkpoint
    boa.env.time_travel(4 * WEEK)

    # Alice got some rewards again since lm callback is unkilled
    with boa.env.anchor():
        rewards_alice = lm_callback.claimable_tokens(alice)
    assert rewards_alice > 0
    crv_balance = crv.balanceOf(alice)
    minter.mint(lm_callback.address, sender=alice)
    assert crv.balanceOf(alice) - crv_balance == rewards_alice
