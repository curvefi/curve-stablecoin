import boa
import pytest
from random import random, randrange, choice

MAX_UINT256 = 2**256 - 1
YEAR = 365 * 86400
WEEK = 7 * 86400


def test_simple_exchange(
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
    alice, bob = accounts[:2]
    boa.env.time_travel(seconds=2 * WEEK + 5)

    # Let Alice and Bob have about the same collateral token amount
    with boa.env.prank(admin):
        boa.deal(collateral_token, alice, 1000 * 10**18)
        boa.deal(collateral_token, bob, 1000 * 10**18)

    # Alice and Bob create loan
    market_controller.create_loan(10**21, 10**21 * 2600, 10, sender=alice)
    market_controller.create_loan(10**21, 10**21 * 1000, 10, sender=bob)

    # Time travel and checkpoint
    boa.env.time_travel(4 * WEEK)
    lm_callback.user_checkpoint(alice, sender=alice)
    lm_callback.user_checkpoint(bob, sender=bob)

    rewards_alice = lm_callback.integrate_fraction(alice)
    rewards_bob = lm_callback.integrate_fraction(bob)
    assert rewards_alice == rewards_bob

    # Now Chad makes a trade crvUSD --> collateral and gets a half of Alice's deposit
    market_amm.exchange_dy(0, 1, 10**21 // 2, 2**255, sender=chad)

    # Time travel and checkpoint
    boa.env.time_travel(4 * WEEK)
    lm_callback.user_checkpoint(alice, sender=alice)
    lm_callback.user_checkpoint(bob, sender=bob)
    old_rewards_alice = rewards_alice
    old_rewards_bob = rewards_bob

    # Bob earned 2 times more CRV
    rewards_alice = lm_callback.integrate_fraction(alice)
    rewards_bob = lm_callback.integrate_fraction(bob)
    d_alice = rewards_alice - old_rewards_alice
    d_bob = rewards_bob - old_rewards_bob
    assert d_bob / d_alice == pytest.approx(2, rel=1e-15)

    minter.mint(lm_callback.address, sender=alice)
    assert crv.balanceOf(alice) == rewards_alice

    minter.mint(lm_callback.address, sender=bob)
    assert crv.balanceOf(bob) == rewards_bob


def test_gauge_integral_with_exchanges(
    accounts,
    admin,
    chad,
    collateral_token,
    crv,
    lm_callback,
    market_controller,
    market_amm,
    price_oracle,
    minter,
):
    with boa.env.anchor():
        alice, bob = accounts[:2]

        integral = 0  # ∫(balance * rate(t) / totalSupply(t) dt)
        checkpoint = boa.env.timestamp
        checkpoint_rate = crv.rate()
        checkpoint_supply = 0
        checkpoint_balance = 0

        boa.env.time_travel(seconds=WEEK)

        # Let Alice and Bob have about the same collateral token amount
        with boa.env.prank(admin):
            boa.deal(collateral_token, alice, 1000 * 10**18)
            boa.deal(collateral_token, bob, 1000 * 10**18)

        def update_integral():
            nonlocal \
                checkpoint, \
                checkpoint_rate, \
                integral, \
                checkpoint_balance, \
                checkpoint_supply

            t1 = boa.env.timestamp
            t_epoch = crv.start_epoch_time_write(sender=admin)
            rate1 = crv.rate()
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
            checkpoint_supply = collateral_token.balanceOf(market_amm)
            checkpoint_balance = market_amm.get_sum_xy(alice)[1]

        # Now let's have a loop where Bob always deposit or withdraws,
        # and Alice does so more rarely
        for i in range(40):
            is_alice = random() < 0.2
            dt = randrange(1, YEAR // 5)
            boa.env.time_travel(seconds=dt)
            print("Time travel", dt)

            # For Bob
            with boa.env.prank(bob):
                collateral_in_amm_bob, stablecoin_in_amm_bob, debt_bob, __ = (
                    market_controller.user_state(bob)
                )
                is_withdraw_bob = (collateral_in_amm_bob > 0) * (random() < 0.5)
                is_underwater_bob = stablecoin_in_amm_bob > 0

                if is_withdraw_bob:
                    amount_bob = randrange(1, collateral_in_amm_bob + 1)
                    if amount_bob == collateral_in_amm_bob:
                        print("Bob repays (full):", debt_bob)
                        print("Bob withdraws (full):", amount_bob)
                        market_controller.repay(debt_bob)
                        assert market_amm.get_sum_xy(bob)[1] == pytest.approx(
                            lm_callback.user_collateral(bob), rel=1e-13
                        )
                    elif market_controller.health(bob) > 0:
                        repay_amount_bob = int(
                            debt_bob // 10 + (debt_bob * 9 // 10) * random() * 0.99
                        )
                        print("Bob repays:", repay_amount_bob)
                        market_controller.repay(repay_amount_bob)
                        if not is_underwater_bob:
                            min_collateral_required_bob = (
                                market_controller.min_collateral(
                                    debt_bob - repay_amount_bob, 10
                                )
                            )
                            remove_amount_bob = min(
                                collateral_in_amm_bob - min_collateral_required_bob,
                                amount_bob,
                            )
                            remove_amount_bob = max(remove_amount_bob, 0)
                            if remove_amount_bob > 0:
                                print("Bob withdraws:", remove_amount_bob)
                                market_controller.remove_collateral(remove_amount_bob)
                            assert market_amm.get_sum_xy(bob)[1] == pytest.approx(
                                lm_callback.user_collateral(bob), rel=1e-13
                            )
                    update_integral()
                elif not is_underwater_bob:
                    amount_bob = randrange(1, collateral_token.balanceOf(bob) // 10 + 1)
                    collateral_token.approve(market_controller.address, amount_bob)
                    max_borrowable_bob = market_controller.max_borrowable(
                        amount_bob + collateral_in_amm_bob, 10, debt_bob
                    )
                    borrow_amount_bob = min(
                        int(random() * (max_borrowable_bob - debt_bob)),
                        max_borrowable_bob - debt_bob,
                    )
                    if borrow_amount_bob > 0:
                        print("Bob deposits:", amount_bob, borrow_amount_bob)
                        if market_controller.loan_exists(bob):
                            market_controller.borrow_more(amount_bob, borrow_amount_bob)
                        else:
                            market_controller.create_loan(
                                amount_bob, borrow_amount_bob, 10
                            )
                        update_integral()
                    assert market_amm.get_sum_xy(bob)[1] == pytest.approx(
                        lm_callback.user_collateral(bob), rel=1e-13
                    )

            # For Alice
            if is_alice:
                with boa.env.prank(alice):
                    collateral_in_amm_alice, stablecoin_in_amm_alice, debt_alice, __ = (
                        market_controller.user_state(alice)
                    )
                    is_withdraw_alice = (collateral_in_amm_alice > 0) * (random() < 0.5)
                    is_underwater_alice = stablecoin_in_amm_alice > 0

                    if is_withdraw_alice:
                        amount_alice = randrange(1, collateral_in_amm_alice + 1)
                        if amount_alice == collateral_in_amm_alice:
                            print("Alice repays (full):", debt_alice)
                            print("Alice withdraws (full):", amount_alice)
                            market_controller.repay(debt_alice)
                            assert market_amm.get_sum_xy(alice)[1] == pytest.approx(
                                lm_callback.user_collateral(alice), rel=1e-13
                            )
                        elif market_controller.health(alice) > 0:
                            repay_amount_alice = int(
                                debt_alice // 10
                                + (debt_alice * 9 // 10) * random() * 0.99
                            )
                            print("Alice repays:", repay_amount_alice)
                            market_controller.repay(repay_amount_alice)
                            if not is_underwater_alice:
                                min_collateral_required_alice = (
                                    market_controller.min_collateral(
                                        debt_alice - repay_amount_alice, 10
                                    )
                                )
                                remove_amount_alice = min(
                                    collateral_in_amm_alice
                                    - min_collateral_required_alice,
                                    amount_alice,
                                )
                                remove_amount_alice = max(remove_amount_alice, 0)
                                if remove_amount_alice > 0:
                                    print("Alice withdraws:", remove_amount_alice)
                                    market_controller.remove_collateral(
                                        remove_amount_alice
                                    )
                            assert market_amm.get_sum_xy(alice)[1] == pytest.approx(
                                lm_callback.user_collateral(alice), rel=1e-13
                            )
                        update_integral()
                    elif not is_underwater_alice:
                        amount_alice = randrange(
                            1, collateral_token.balanceOf(alice) // 10 + 1
                        )
                        collateral_token.approve(
                            market_controller.address, amount_alice
                        )
                        max_borrowable_alice = market_controller.max_borrowable(
                            amount_alice + collateral_in_amm_alice, 10, debt_alice
                        )
                        borrow_amount_alice = min(
                            int(random() * (max_borrowable_alice - debt_alice)),
                            max_borrowable_alice - debt_alice,
                        )
                        if borrow_amount_alice > 0:
                            print("Alice deposits:", amount_alice, borrow_amount_alice)
                            if market_controller.loan_exists(alice):
                                market_controller.borrow_more(
                                    amount_alice, borrow_amount_alice
                                )
                            else:
                                market_controller.create_loan(
                                    amount_alice, borrow_amount_alice, 10
                                )
                            update_integral()
                        assert market_amm.get_sum_xy(alice)[1] == pytest.approx(
                            lm_callback.user_collateral(alice), rel=1e-13
                        )

            # Chad trading
            alice_bands = market_amm.read_user_tick_numbers(alice)
            alice_bands = (
                []
                if alice_bands[0] == alice_bands[1]
                else list(range(alice_bands[0], alice_bands[1] + 1))
            )
            bob_bands = market_amm.read_user_tick_numbers(bob)
            bob_bands = (
                []
                if bob_bands[0] == bob_bands[1]
                else list(range(bob_bands[0], bob_bands[1] + 1))
            )
            available_bands = alice_bands + bob_bands
            print("Bob bands:", bob_bands)
            print("Alice bands:", alice_bands)
            print("Active band:", market_amm.active_band())
            p_o = market_amm.price_oracle()
            upper_bands = sorted(
                list(
                    filter(
                        lambda band: market_amm.p_oracle_down(band) > p_o,
                        available_bands,
                    )
                )
            )[-5:]
            lower_bands = sorted(
                list(
                    filter(
                        lambda band: market_amm.p_oracle_up(band) < p_o, available_bands
                    )
                )
            )[:5]
            available_bands = upper_bands + lower_bands
            if len(available_bands) > 0:
                target_band = choice(available_bands)
                p_up = market_amm.p_oracle_up(target_band)
                p_down = market_amm.p_oracle_down(target_band)
                p_target = int(p_down + random() * (p_up - p_down))
                price_oracle.set_price(p_target, sender=admin)
                print("Price set to:", p_target)
                amount, pump = market_amm.get_amount_for_price(p_target)
                with boa.env.prank(chad):
                    if pump:
                        market_amm.exchange(0, 1, amount, 0)
                    else:
                        market_amm.exchange(1, 0, amount, 0)
                print("Swap:", amount, pump)
                print("Active band:", market_amm.active_band())
                update_integral()

            # Checking that updating the checkpoint in the same second does nothing
            # Also everyone can update: that should make no difference, too
            if random() < 0.5:
                lm_callback.user_checkpoint(alice, sender=alice)
            if random() < 0.5:
                lm_callback.user_checkpoint(bob, sender=bob)

            dt = randrange(1, YEAR // 20)
            boa.env.time_travel(seconds=dt)
            print("Time travel", dt)

            total_collateral_from_amm = collateral_token.balanceOf(market_amm)
            total_collateral_from_lm_cb = lm_callback.total_collateral()
            print(
                "Total collateral:",
                total_collateral_from_amm,
                total_collateral_from_lm_cb,
            )
            if total_collateral_from_amm > 0 and total_collateral_from_lm_cb > 0:
                assert total_collateral_from_amm == pytest.approx(
                    total_collateral_from_lm_cb, rel=1e-13
                )

            with boa.env.prank(alice):
                crv_balance = crv.balanceOf(alice)
                with boa.env.anchor():
                    crv_reward = lm_callback.claimable_tokens(alice)
                minter.mint(lm_callback.address)
                assert crv.balanceOf(alice) - crv_balance == crv_reward

                update_integral()
                print(i, dt / 86400, integral, lm_callback.integrate_fraction(alice))
                assert lm_callback.integrate_fraction(alice) == pytest.approx(
                    integral, rel=1e-14
                )

            with boa.env.prank(bob):
                crv_balance = crv.balanceOf(bob)
                with boa.env.anchor():
                    crv_reward = lm_callback.claimable_tokens(bob)
                minter.mint(lm_callback.address)
                assert crv.balanceOf(bob) - crv_balance == crv_reward


def test_full_repay_underwater(
    accounts,
    admin,
    chad,
    collateral_token,
    crv,
    lm_callback,
    market_controller,
    market_amm,
    price_oracle,
    minter,
):
    with boa.env.anchor():
        alice, bob = accounts[:2]

        # Let Alice and Bob have about the same collateral token amount
        with boa.env.prank(admin):
            boa.deal(collateral_token, alice, 1000 * 10**18)
            boa.deal(collateral_token, bob, 1000 * 10**18)

        dt = randrange(1, YEAR // 5)
        boa.env.time_travel(seconds=dt)

        # Bob creates loan
        with boa.env.prank(bob):
            amount_bob = 10**20
            collateral_token.approve(market_controller.address, amount_bob)
            market_controller.create_loan(amount_bob, int(amount_bob * 2000), 10)
            print("Bob deposits:", amount_bob)

        # Alice creates loan
        with boa.env.prank(alice):
            amount_alice = 10**20
            collateral_token.approve(market_controller.address, amount_alice)
            market_controller.create_loan(amount_alice, int(amount_alice * 500), 10)
            print("Alice deposits:", amount_alice)

        print(collateral_token.balanceOf(market_amm), lm_callback.total_collateral())

        dt = randrange(1, YEAR // 5)
        boa.env.time_travel(seconds=dt)

        # Chad trading. As a result Bob will be underwater
        bob_bands = market_amm.read_user_tick_numbers(bob)
        bob_bands = list(range(bob_bands[0], bob_bands[1] + 1))
        print("Bob bands:", bob_bands)
        print("Active band:", market_amm.active_band())
        target_band = bob_bands[7]
        p_up = market_amm.p_oracle_up(target_band)
        p_down = market_amm.p_oracle_down(target_band)
        p_target = int((p_down + p_up) / 2)
        price_oracle.set_price(p_target, sender=admin)
        print("Price set to:", p_target)
        amount, pump = market_amm.get_amount_for_price(p_target)
        with boa.env.prank(chad):
            if pump:
                market_amm.exchange(0, 1, amount, 0)
            else:
                market_amm.exchange(1, 0, amount, 0)
        print("Swap:", amount, pump, "\n")
        print("Active band:", market_amm.active_band())

        # Bob fully repays being underwater
        debt_bob = market_controller.user_state(bob)[2]
        market_controller.repay(debt_bob, sender=bob)
        print("Bob repays (full):", debt_bob)
        print("Bob withdraws (full):", amount_bob)

        total_collateral_from_amm = collateral_token.balanceOf(market_amm)
        total_collateral_from_lm_cb = lm_callback.total_collateral()
        print(
            "Total collateral:", total_collateral_from_amm, total_collateral_from_lm_cb
        )
        assert total_collateral_from_amm == pytest.approx(
            total_collateral_from_lm_cb, rel=1e-15
        )

        for user in accounts[:2]:
            with boa.env.prank(user):
                crv_balance = crv.balanceOf(user)
                with boa.env.anchor():
                    crv_reward = lm_callback.claimable_tokens(bob)
                minter.mint(lm_callback.address)
                assert crv.balanceOf(user) - crv_balance == crv_reward
