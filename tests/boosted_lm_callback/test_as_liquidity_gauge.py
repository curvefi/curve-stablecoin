import boa
from random import random, randrange
from ..conftest import approx
from math import log

MAX_UINT256 = 2 ** 256 - 1
YEAR = 365 * 86400
WEEK = 7 * 86400


def test_gauge_integral_one_user(accounts, admin, collateral_token, crv, boosted_lm_callback, gauge_controller, market_controller, stablecoin):
    with boa.env.anchor():
        alice, bob = accounts[:2]

        # Wire up Gauge to the controller to have proper rates and stuff
        with boa.env.prank(admin):
            gauge_controller.add_type("crvUSD Market")
            gauge_controller.change_type_weight(0, 10 ** 18)
            gauge_controller.add_gauge(boosted_lm_callback.address, 0, 10 ** 18)

        boa.env.time_travel(seconds=WEEK)
        alice_staked = 0
        integral = 0  # ∫(balance * rate(t) / totalSupply(t) dt)
        checkpoint = boa.env.vm.patch.timestamp
        # boa.env.time_travel(blocks=1)
        checkpoint_rate = crv.rate()
        checkpoint_supply = 0
        checkpoint_balance = 0

        collateral_token._mint_for_testing(alice, 1000 * 10**18, sender=admin)

        def update_integral():
            nonlocal checkpoint, checkpoint_rate, integral, checkpoint_balance, checkpoint_supply

            t1 = boa.env.vm.patch.timestamp
            # boa.env.time_travel(blocks=1)
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
            checkpoint_supply = boosted_lm_callback.total_collateral()
            checkpoint_balance = boosted_lm_callback.user_collateral(alice)

        for i in range(40):
            dt = 3 * (i + 1) * 86400
            boa.env.time_travel(seconds=dt)

            if i > -1:
                with boa.env.prank(alice):
                    collateral_in_amm = market_controller.user_state(alice)[0]
                    collateral_alice = boosted_lm_callback.user_collateral(alice)
                    assert collateral_in_amm == collateral_alice
                    print("Alice deposits")

                    amount_alice = collateral_token.balanceOf(alice) // 5
                    collateral_token.approve(market_controller.address, amount_alice)
                    if market_controller.loan_exists(alice):
                        # market_controller.borrow_more(amount_alice, amount_alice * 1000)
                        market_controller.add_collateral(amount_alice)
                    else:
                        market_controller.create_loan(amount_alice, amount_alice * 1000, 10)
                    update_integral()
                    alice_staked += amount_alice

            assert boosted_lm_callback.user_collateral(alice) == alice_staked
            assert boosted_lm_callback.total_collateral() == alice_staked

            dt = (i + 1) * 10 * 86400
            boa.env.time_travel(seconds=dt)

            boosted_lm_callback.user_checkpoint(alice, sender=alice)
            update_integral()
            print(i, dt / 86400, integral, boosted_lm_callback.integrate_fraction(alice))
            if integral > 0 and boosted_lm_callback.integrate_fraction(alice) > 0:
                assert approx(boosted_lm_callback.integrate_fraction(alice), integral, 1e-15)


def test_gauge_integral(accounts, admin, collateral_token, crv, boosted_lm_callback, gauge_controller, market_controller, stablecoin):
    with boa.env.anchor():
        alice, bob = accounts[:2]

        # Wire up Gauge to the controller to have proper rates and stuff
        with boa.env.prank(admin):
            gauge_controller.add_type("crvUSD Market")
            gauge_controller.change_type_weight(0, 10 ** 18)
            gauge_controller.add_gauge(boosted_lm_callback.address, 0, 10 ** 18)

        alice_staked = 0
        bob_staked = 0
        integral = 0  # ∫(balance * rate(t) / totalSupply(t) dt)
        checkpoint = boa.env.vm.patch.timestamp
        boa.env.time_travel(blocks=1)
        checkpoint_rate = crv.rate()
        checkpoint_supply = 0
        checkpoint_balance = 0

        # Let Alice and Bob have about the same token amount
        with boa.env.prank(admin):
            collateral_token._mint_for_testing(alice, 1000 * 10**18)
            collateral_token._mint_for_testing(bob, 1000 * 10**18)

        def update_integral():
            nonlocal checkpoint, checkpoint_rate, integral, checkpoint_balance, checkpoint_supply

            t1 = boa.env.vm.patch.timestamp
            boa.env.time_travel(blocks=1)
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
            checkpoint_supply = boosted_lm_callback.total_collateral()
            checkpoint_balance = boosted_lm_callback.user_collateral(alice)

        # Now let's have a loop where Bob always deposit or withdraws,
        # and Alice does so more rarely
        for i in range(40):
            is_alice = random() < 0.2
            dt = randrange(1, YEAR // 5)
            boa.env.time_travel(seconds=dt)

            # For Bob
            with boa.env.prank(bob):
                is_withdraw = (i > 0) * (random() < 0.5)
                print("Bob", "withdraws" if is_withdraw else "deposits")
                if is_withdraw:
                    collateral_in_amm, _, debt, __ = market_controller.user_state(bob)
                    collateral_bob = boosted_lm_callback.user_collateral(bob)
                    assert collateral_in_amm == collateral_bob
                    amount = randrange(1, collateral_in_amm + 1)
                    if amount == collateral_in_amm:
                        market_controller.repay(debt)
                    else:
                        market_controller.repay(amount * 1000)
                        market_controller.remove_collateral(amount)
                    update_integral()
                    bob_staked -= amount
                else:
                    amount = randrange(1, collateral_token.balanceOf(bob) // 10 + 1)
                    collateral_token.approve(market_controller.address, amount)
                    if market_controller.loan_exists(bob):
                        market_controller.borrow_more(amount, amount * 1000)
                    else:
                        market_controller.create_loan(amount, amount * 1000, 10)
                    update_integral()
                    bob_staked += amount

            if is_alice:
                # For Alice
                with boa.env.prank(alice):
                    collateral_in_amm = market_controller.user_state(alice)[0]
                    collateral_alice = boosted_lm_callback.user_collateral(alice)
                    assert collateral_in_amm == collateral_alice
                    is_withdraw_alice = (collateral_in_amm > 0) * (random() < 0.5)
                    print("Alice", "withdraws" if is_withdraw_alice else "deposits")

                    if is_withdraw_alice:
                        amount_alice = randrange(1, collateral_in_amm + 1)
                        market_controller.repay(amount_alice * 1000)
                        # market_controller.remove_collateral(amount_alice)
                        update_integral()
                        # alice_staked -= amount_alice
                    else:
                        amount_alice = randrange(1, collateral_token.balanceOf(alice) // 10 + 1)
                        collateral_token.approve(market_controller.address, amount_alice)
                        if market_controller.loan_exists(alice):
                            market_controller.borrow_more(amount_alice, amount_alice * 1000)
                        else:
                            market_controller.create_loan(amount_alice, amount_alice * 1000, 10)
                        update_integral()
                        alice_staked += amount_alice


            # Checking that updating the checkpoint in the same second does nothing
            # Also everyone can update: that should make no difference, too
            if random() < 0.5:
                boosted_lm_callback.user_checkpoint(alice, sender=alice)
            if random() < 0.5:
                boosted_lm_callback.user_checkpoint(bob, sender=bob)

            assert boosted_lm_callback.user_collateral(alice) == alice_staked
            assert boosted_lm_callback.user_collateral(bob) == bob_staked
            assert boosted_lm_callback.total_collateral() == alice_staked + bob_staked

            dt = randrange(1, YEAR // 20)
            boa.env.time_travel(seconds=dt)

            boosted_lm_callback.user_checkpoint(alice, sender=alice)
            update_integral()
            print(i, dt / 86400, integral, boosted_lm_callback.integrate_fraction(alice))
            assert approx(boosted_lm_callback.integrate_fraction(alice), integral, 1e-15)


# def test_mining_with_votelock(
#     accounts,
#     chain,
#     history,
#     collateral_token,
#     token,
#     gauge_v3,
#     gauge_controller,
#     voting_escrow,
# ):
#     alice, bob = accounts[:2]
#     chain.sleep(2 * WEEK + 5)
#
#     # Wire up Gauge to the controller to have proper rates and stuff
#     gauge_controller.add_type(b"Liquidity", {"from": alice})
#     gauge_controller.change_type_weight(0, 10 ** 18, {"from": alice})
#     gauge_controller.add_gauge(gauge_v3.address, 0, 10 ** 18, {"from": alice})
#
#     # Prepare tokens
#     token.transfer(bob, 10 ** 20, {"from": alice})
#     token.approve(voting_escrow, MAX_UINT256, {"from": alice})
#     token.approve(voting_escrow, MAX_UINT256, {"from": bob})
#     collateral_token.transfer(bob, collateral_token.balanceOf(alice) // 2, {"from": alice})
#     collateral_token.approve(gauge_v3.address, MAX_UINT256, {"from": alice})
#     collateral_token.approve(gauge_v3.address, MAX_UINT256, {"from": bob})
#
#     # Alice deposits to escrow. She now has a BOOST
#     t = chain[-1].timestamp
#     voting_escrow.create_lock(10 ** 20, t + 2 * WEEK, {"from": alice})
#
#     # Alice and Bob deposit some liquidity
#     gauge_v3.deposit(10 ** 21, {"from": alice})
#     gauge_v3.deposit(10 ** 21, {"from": bob})
#
#     # Time travel and checkpoint
#     chain.sleep(4 * WEEK)
#     alice.transfer(alice, 1)
#     while True:
#         gauge_v3.user_checkpoint(alice, {"from": alice})
#         gauge_v3.user_checkpoint(bob, {"from": bob})
#         if chain[-1].timestamp != chain[-2].timestamp:
#             chain.undo(2)
#         else:
#             break
#
#     # 4 weeks down the road, balanceOf must be 0
#     assert voting_escrow.balanceOf(alice) == 0
#     assert voting_escrow.balanceOf(bob) == 0
#
#     # Alice earned 2.5 times more CRV because she vote-locked her CRV
#     rewards_alice = gauge_v3.integrate_fraction(alice)
#     rewards_bob = gauge_v3.integrate_fraction(bob)
#     assert approx(rewards_alice / rewards_bob, 2.5, 1e-5)
#
#     # Time travel / checkpoint: no one has CRV vote-locked
#     chain.sleep(4 * WEEK)
#     alice.transfer(alice, 1)
#     voting_escrow.withdraw({"from": alice})
#     while True:
#         gauge_v3.user_checkpoint(alice, {"from": alice})
#         gauge_v3.user_checkpoint(bob, {"from": bob})
#         if chain[-1].timestamp != chain[-2].timestamp:
#             chain.undo(2)
#         else:
#             break
#     old_rewards_alice = rewards_alice
#     old_rewards_bob = rewards_bob
#
#     # Alice earned the same as Bob now
#     rewards_alice = gauge_v3.integrate_fraction(alice)
#     rewards_bob = gauge_v3.integrate_fraction(bob)
#     d_alice = rewards_alice - old_rewards_alice
#     d_bob = rewards_bob - old_rewards_bob
#     assert d_alice == d_bob
#
#     # Both Alice and Bob votelock
#     while True:
#         t = chain[-1].timestamp
#         voting_escrow.create_lock(10 ** 20, t + 2 * WEEK, {"from": alice})
#         voting_escrow.create_lock(10 ** 20, t + 2 * WEEK, {"from": bob})
#         if chain[-1].timestamp != chain[-2].timestamp:
#             chain.undo(2)
#         else:
#             break
#
#     # Time travel / checkpoint: no one has CRV vote-locked
#     chain.sleep(4 * WEEK)
#     alice.transfer(alice, 1)
#     voting_escrow.withdraw({"from": alice})
#     voting_escrow.withdraw({"from": bob})
#     while True:
#         gauge_v3.user_checkpoint(alice, {"from": alice})
#         gauge_v3.user_checkpoint(bob, {"from": bob})
#         if chain[-1].timestamp != chain[-2].timestamp:
#             chain.undo(2)
#         else:
#             break
#     old_rewards_alice = rewards_alice
#     old_rewards_bob = rewards_bob
#
#     # Alice earned the same as Bob now
#     rewards_alice = gauge_v3.integrate_fraction(alice)
#     rewards_bob = gauge_v3.integrate_fraction(bob)
#     d_alice = rewards_alice - old_rewards_alice
#     d_bob = rewards_bob - old_rewards_bob
#     assert d_alice == d_bob
