import boa
from random import random, randrange, choice
from ..conftest import approx

MAX_UINT256 = 2 ** 256 - 1
YEAR = 365 * 86400
WEEK = 7 * 86400


def test_simple_exchange(
        accounts,
        admin,
        collateral_token,
        crv,
        market_controller,
        market_amm,
        boosted_lm_callback,
        gauge_controller,
        voting_escrow,
):
    alice, bob, chad = accounts[:3]
    boa.env.time_travel(seconds=2 * WEEK + 5)

    # Wire up Gauge to the controller to have proper rates and stuff
    with boa.env.prank(admin):
        gauge_controller.add_type("crvUSD Market")
        gauge_controller.change_type_weight(0, 10 ** 18)
        gauge_controller.add_gauge(boosted_lm_callback.address, 0, 10 ** 18)

    # Let Alice and Bob have about the same collateral token amount
    with boa.env.prank(admin):
        collateral_token._mint_for_testing(alice, 1000 * 10 ** 18)
        collateral_token._mint_for_testing(bob, 1000 * 10 ** 18)
        collateral_token._mint_for_testing(chad, 10**8 * 10 ** 18)

    collateral_token.approve(market_controller.address, MAX_UINT256, sender=alice)
    collateral_token.approve(market_controller.address, MAX_UINT256, sender=bob)
    collateral_token.approve(market_amm.address, MAX_UINT256, sender=chad)

    # Alice and Bob create loan
    market_controller.create_loan(10**21, 10**21 * 2600, 10, sender=alice)
    market_controller.create_loan(10**21, 10**21 * 1000, 10, sender=bob)
    # Chad creates loan just to get crvUSD
    market_controller.create_loan(10**25, 10**25, 10, sender=chad)

    # Time travel and checkpoint
    boa.env.time_travel(4 * WEEK)
    boosted_lm_callback.user_checkpoint(alice, sender=alice)
    boosted_lm_callback.user_checkpoint(bob, sender=bob)

    rewards_alice = boosted_lm_callback.integrate_fraction(alice)
    rewards_bob = boosted_lm_callback.integrate_fraction(bob)
    assert rewards_alice == rewards_bob

    # Now Chad makes a trade crvUSD --> collateral and gets a half of Alice's deposit
    market_amm.exchange_dy(0, 1, 10**21 // 2, 2**255, sender=chad)

    # Time travel and checkpoint
    boa.env.time_travel(4 * WEEK)
    boosted_lm_callback.user_checkpoint(alice, sender=alice)
    boosted_lm_callback.user_checkpoint(bob, sender=bob)
    old_rewards_alice = rewards_alice
    old_rewards_bob = rewards_bob

    # Bob earned 2 times more CRV
    rewards_alice = boosted_lm_callback.integrate_fraction(alice)
    rewards_bob = boosted_lm_callback.integrate_fraction(bob)
    d_alice = rewards_alice - old_rewards_alice
    d_bob = rewards_bob - old_rewards_bob
    assert approx(d_bob / d_alice, 2, 1e-15)


def test_gauge_integral_with_exchanges(
        accounts,
        admin,
        collateral_token,
        crv,
        boosted_lm_callback,
        gauge_controller,
        market_controller,
        market_amm,
        price_oracle,
):
    with boa.env.anchor():
        alice, bob, chad = accounts[:3]

        # Wire up Gauge to the controller to have proper rates and stuff
        with boa.env.prank(admin):
            gauge_controller.add_type("crvUSD Market")
            gauge_controller.change_type_weight(0, 10 ** 18)
            gauge_controller.add_gauge(boosted_lm_callback.address, 0, 10 ** 18)

        integral = 0  # ∫(balance * rate(t) / totalSupply(t) dt)
        checkpoint = boa.env.vm.patch.timestamp
        checkpoint_rate = crv.rate()
        checkpoint_supply = 0
        checkpoint_balance = 0

        # Let Alice and Bob have about the same collateral token amount
        with boa.env.prank(admin):
            collateral_token._mint_for_testing(alice, 1000 * 10**18)
            collateral_token._mint_for_testing(bob, 1000 * 10**18)

        # Chad creates loan just to get crvUSD
        collateral_token._mint_for_testing(chad, 10**26, sender=admin)
        market_controller.create_loan(10 ** 25, 10 ** 24, 10, sender=chad)
        chad_n = market_amm.read_user_tick_numbers(chad)[0]

        def update_integral():
            nonlocal checkpoint, checkpoint_rate, integral, checkpoint_balance, checkpoint_supply

            t1 = boa.env.vm.patch.timestamp
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
            checkpoint_supply = collateral_token.balanceOf(market_amm) - market_amm.admin_fees_y()
            checkpoint_balance = market_amm.get_sum_xy(alice)[1]

        # Now let's have a loop where Bob always deposit or withdraws,
        # and Alice does so more rarely
        for i in range(40):
            is_alice = random() < 0.2
            dt = randrange(1, YEAR // 5)
            boa.env.time_travel(seconds=dt)

            # For Bob
            with boa.env.prank(bob):
                collateral_in_amm_bob, _, debt_bob, __ = market_controller.user_state(bob)
                is_withdraw_bob = (collateral_in_amm_bob > 0) * (random() < 0.5)
                is_underwater_bob = market_amm.get_sum_xy(bob)[0] > 0
                if is_withdraw_bob:
                    amount_bob = randrange(1, collateral_in_amm_bob + 1)
                    if amount_bob == collateral_in_amm_bob:
                        market_controller.repay(debt_bob)
                        print("Bob repays (full):", debt_bob)
                        print("Bob withdraws (full):", amount_bob)
                        # assert market_amm.get_sum_xy(bob)[1] == boosted_lm_callback.user_collateral(bob)
                    else:
                        repay_amount_bob = int(debt_bob // 10 + (debt_bob * 9 // 10) * random() * 0.99)
                        market_controller.repay(repay_amount_bob)
                        print("Bob repays:", repay_amount_bob)
                        if not is_underwater_bob:
                            min_collateral_required_bob = market_controller.min_collateral(debt_bob - repay_amount_bob, 10)
                            remove_amount_bob = min(collateral_in_amm_bob - min_collateral_required_bob, amount_bob)
                            market_controller.remove_collateral(remove_amount_bob)
                            print("Bob withdraws:", remove_amount_bob)
                            # assert market_amm.get_sum_xy(bob)[1] == boosted_lm_callback.user_collateral(bob)
                    update_integral()
                elif not is_underwater_bob:
                    amount_bob = randrange(1, collateral_token.balanceOf(bob) // 10 + 1)
                    collateral_token.approve(market_controller.address, amount_bob)
                    p = price_oracle.price_w(sender=admin) * 0.7 / 10 ** 18
                    borrow_amount_bob = int(amount_bob * random() * p)
                    if market_controller.loan_exists(bob):
                        market_controller.borrow_more(amount_bob, borrow_amount_bob)
                    else:
                        market_controller.create_loan(amount_bob, borrow_amount_bob, 10)
                    print("Bob deposits:", amount_bob, borrow_amount_bob)
                    update_integral()
                    # assert market_amm.get_sum_xy(bob)[1] == boosted_lm_callback.user_collateral(bob)

            # For Alice
            if is_alice:
                with boa.env.prank(alice):
                    collateral_in_amm_alice, _, debt_alice, __ = market_controller.user_state(alice)
                    is_withdraw_alice = (collateral_in_amm_alice > 0) * (random() < 0.5)
                    is_underwater_alice = market_amm.get_sum_xy(alice)[0] > 0

                    if is_withdraw_alice:
                        amount_alice = randrange(1, collateral_in_amm_alice + 1)
                        if amount_alice == collateral_in_amm_alice:
                            market_controller.repay(debt_alice)
                            print("Alice repays (full):", debt_alice)
                            print("Alice withdraws (full):", amount_alice)
                            # assert market_amm.get_sum_xy(alice)[1] == boosted_lm_callback.user_collateral(alice)
                        else:
                            repay_amount_alice = int(debt_alice // 10 + (debt_alice * 9 // 10) * random() * 0.99)
                            market_controller.repay(repay_amount_alice)
                            print("Alice repays:", repay_amount_alice)
                            if not is_underwater_alice:
                                min_collateral_required_alice = market_controller.min_collateral(debt_alice - repay_amount_alice, 10)
                                remove_amount_alice = min(collateral_in_amm_alice - min_collateral_required_alice, amount_alice)
                                market_controller.remove_collateral(remove_amount_alice)
                                print("Alice withdraws:", remove_amount_alice)
                                # assert market_amm.get_sum_xy(alice)[1] == boosted_lm_callback.user_collateral(alice)
                        update_integral()
                    elif not is_underwater_alice:
                        amount_alice = randrange(1, collateral_token.balanceOf(alice) // 10 + 1)
                        collateral_token.approve(market_controller.address, amount_alice)
                        max_borrowable = market_controller.max_borrowable(amount_alice + collateral_in_amm_alice, 10, debt_alice)
                        borrow_amount_alice = int(random() * (max_borrowable - debt_alice))
                        if market_controller.loan_exists(alice):
                            market_controller.borrow_more(amount_alice, borrow_amount_alice)
                        else:
                            market_controller.create_loan(amount_alice, borrow_amount_alice, 10)
                        print("Alice deposits:", amount_alice, borrow_amount_alice)
                        update_integral()
                        # assert market_amm.get_sum_xy(alice)[1] == boosted_lm_callback.user_collateral(alice)

            # Chad trading
            alice_bands = market_amm.read_user_tick_numbers(alice)
            alice_bands = list(range(alice_bands[0], alice_bands[1] + 1))
            bob_bands = market_amm.read_user_tick_numbers(bob)
            bob_bands = list(range(bob_bands[0], bob_bands[1] + 1))
            available_bands = list(filter(lambda x: 0 < x < chad_n, alice_bands + bob_bands))
            print("Bob bands:", bob_bands)
            print("Alice bands:", alice_bands)
            print("Active band:", market_amm.active_band())
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
                boosted_lm_callback.user_checkpoint(alice, sender=alice)
            if random() < 0.5:
                boosted_lm_callback.user_checkpoint(bob, sender=bob)

            dt = randrange(1, YEAR // 20)
            boa.env.time_travel(seconds=dt)

            total_collateral_from_amm = collateral_token.balanceOf(market_amm) - market_amm.admin_fees_y() - 10 ** 25
            total_collateral_from_lm_cb = boosted_lm_callback.total_collateral() - 10 ** 25
            working_collateral_from_lm_cb = boosted_lm_callback.working_supply() - 10 ** 25 * 4 // 10
            print("Total collateral:", total_collateral_from_amm, total_collateral_from_lm_cb)
            print("Working collateral:", total_collateral_from_amm * 4 // 10, working_collateral_from_lm_cb)
            if total_collateral_from_amm > 0 and total_collateral_from_lm_cb > 0:
                assert approx(total_collateral_from_amm, total_collateral_from_lm_cb, 1e-11)
                assert approx(total_collateral_from_amm * 4 // 10, working_collateral_from_lm_cb, 1e-11)

            boosted_lm_callback.user_checkpoint(alice, sender=alice)
            update_integral()
            print(i, dt / 86400, integral, boosted_lm_callback.integrate_fraction(alice), "\n")
            assert approx(boosted_lm_callback.integrate_fraction(alice), integral, 1e-10)


def test_full_repay_underwater(
        accounts,
        admin,
        collateral_token,
        crv,
        boosted_lm_callback,
        gauge_controller,
        market_controller,
        market_amm,
        price_oracle,
):
    with boa.env.anchor():
        alice, bob, chad = accounts[:3]

        # Wire up Gauge to the controller to have proper rates and stuff
        with boa.env.prank(admin):
            gauge_controller.add_type("crvUSD Market")
            gauge_controller.change_type_weight(0, 10 ** 18)
            gauge_controller.add_gauge(boosted_lm_callback.address, 0, 10 ** 18)

        integral = 0  # ∫(balance * rate(t) / totalSupply(t) dt)

        # Let Alice and Bob have about the same collateral token amount
        with boa.env.prank(admin):
            collateral_token._mint_for_testing(alice, 1000 * 10**18)
            collateral_token._mint_for_testing(bob, 1000 * 10**18)

        # Chad creates loan just to get crvUSD
        collateral_token._mint_for_testing(chad, 10**26, sender=admin)
        market_controller.create_loan(10 ** 25, 10 ** 24, 10, sender=chad)

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

        print(collateral_token.balanceOf(market_amm) - market_amm.admin_fees_y() - 10 ** 25,
              boosted_lm_callback.total_collateral() - 10 ** 25)
        print(boosted_lm_callback.working_supply() - 10 ** 25 * 4 // 10)

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

        total_collateral_from_amm = collateral_token.balanceOf(market_amm) - market_amm.admin_fees_y() - 10**25
        total_collateral_from_lm_cb = boosted_lm_callback.total_collateral() - 10**25
        working_collateral_from_lm_cb = boosted_lm_callback.working_supply() - 10**25 * 4 // 10
        print("Total collateral:", total_collateral_from_amm, total_collateral_from_lm_cb)
        print("Working collateral:", total_collateral_from_amm * 4 // 10, working_collateral_from_lm_cb)
        assert approx(total_collateral_from_amm, total_collateral_from_lm_cb, 1e-15)
        assert approx(total_collateral_from_amm * 4 // 10, working_collateral_from_lm_cb, 1e-15)


def test_gauge_integral_with_exchanges_rekt(
        accounts,
        admin,
        collateral_token,
        crv,
        boosted_lm_callback,
        gauge_controller,
        market_controller,
        market_amm,
        price_oracle,
):
    with boa.env.anchor():
        alice, bob, chad = accounts[:3]

        # Wire up Gauge to the controller to have proper rates and stuff
        with boa.env.prank(admin):
            gauge_controller.add_type("crvUSD Market")
            gauge_controller.change_type_weight(0, 10 ** 18)
            gauge_controller.add_gauge(boosted_lm_callback.address, 0, 10 ** 18)

        integral = 0  # ∫(balance * rate(t) / totalSupply(t) dt)
        checkpoint = boa.env.vm.patch.timestamp
        checkpoint_rate = crv.rate()
        checkpoint_supply = 0
        checkpoint_balance = 0

        boa.env.time_travel(seconds=WEEK)

        # Let Alice and Bob have about the same collateral token amount
        with boa.env.prank(admin):
            collateral_token._mint_for_testing(alice, 1000 * 10**18)
            collateral_token._mint_for_testing(bob, 1000 * 10**18)

        # Chad creates loan just to get crvUSD
        collateral_token._mint_for_testing(chad, 10**26, sender=admin)
        market_controller.create_loan(10 ** 25, 10 ** 24, 10, sender=chad)

        def update_integral():
            nonlocal checkpoint, checkpoint_rate, integral, checkpoint_balance, checkpoint_supply

            t1 = boa.env.vm.patch.timestamp
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
            checkpoint_supply = collateral_token.balanceOf(market_amm) - market_amm.admin_fees_y()
            checkpoint_balance = market_amm.get_sum_xy(alice)[1]

        # Bob creates loan
        with boa.env.prank(bob):
            amount_bob = 84526027798978669717
            borrow_amount_bob = int(amount_bob * 395)
            collateral_token.approve(market_controller.address, amount_bob)
            market_controller.create_loan(amount_bob, borrow_amount_bob, 10)
            print("Bob deposits:", amount_bob)
            update_integral()

        # # Alice creates loan
        # with boa.env.prank(alice):
        #     amount_alice = 10 ** 20
        #     collateral_token.approve(market_controller.address, amount_alice)
        #     market_controller.create_loan(amount_alice, int(amount_alice * 1700), 10)
        #     print("Alice deposits:", amount_alice)
        #     update_integral()

        for i in range(40):
            dt = randrange(1, YEAR // 5)
            boa.env.time_travel(seconds=dt)

            # debt_bob = market_controller.user_state(bob)[2]
            # repay_amount_bob = int(debt_bob * random() * 0.7)
            # market_controller.repay(repay_amount_bob, sender=bob)
            # print("Bob repays:", repay_amount_bob)
            #
            # debt_alice = market_controller.user_state(alice)[2]
            # repay_amount_alice = int(debt_alice * random() * 0.7)
            # market_controller.repay(repay_amount_alice, sender=alice)
            # print("Alice repays:", repay_amount_alice)

            # Chad trading
            bob_bands = market_amm.read_user_tick_numbers(bob)
            bob_bands = list(range(bob_bands[0], bob_bands[1] + 1))
            alice_bands = market_amm.read_user_tick_numbers(alice)
            alice_bands = list(range(alice_bands[0], alice_bands[1] + 1))
            available_bands = list(filter(lambda x: 0 < x, alice_bands + bob_bands))
            print("Bob bands:", bob_bands)
            print("Alice bands:", alice_bands)
            print("Active band:", market_amm.active_band())
            target_band = choice(alice_bands)
            if i == 39:
                debt_alice = market_controller.user_state(alice)[2]
                repay_amount_alice = int(debt_alice * 0.7)
                market_controller.repay(repay_amount_alice, sender=alice)
                print("Alice repays:", repay_amount_alice)
                target_band = bob_bands[4]
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
                boosted_lm_callback.user_checkpoint(alice, sender=alice)
            if random() < 0.5:
                boosted_lm_callback.user_checkpoint(bob, sender=bob)

            dt = randrange(1, YEAR // 20)
            boa.env.time_travel(seconds=dt)

            total_collateral_from_amm = collateral_token.balanceOf(market_amm) - market_amm.admin_fees_y() - 10 ** 25
            total_collateral_from_lm_cb = boosted_lm_callback.total_collateral() - 10 ** 25
            working_collateral_from_lm_cb = boosted_lm_callback.working_supply() - 10 ** 25 * 4 // 10
            print("Total collateral:", total_collateral_from_amm, total_collateral_from_lm_cb)
            print("Working collateral:", total_collateral_from_amm * 4 // 10, working_collateral_from_lm_cb)
            if total_collateral_from_amm > 0 and total_collateral_from_lm_cb > 0:
                assert approx(total_collateral_from_amm, total_collateral_from_lm_cb, 1e-13)
                assert approx(total_collateral_from_amm * 4 // 10, working_collateral_from_lm_cb, 1e-13)

            boosted_lm_callback.user_checkpoint(alice, sender=alice)
            update_integral()
            print(i, dt / 86400, integral, boosted_lm_callback.integrate_fraction(alice), "\n")
            assert approx(boosted_lm_callback.integrate_fraction(alice), integral, 1e-13)
    raise Exception("Success")


def test_gauge_integral_with_exchanges_rekt2(
        accounts,
        admin,
        collateral_token,
        crv,
        boosted_lm_callback,
        gauge_controller,
        market_controller,
        market_amm,
        price_oracle,
):
    with boa.env.anchor():
        alice, bob, chad = accounts[:3]

        # Wire up Gauge to the controller to have proper rates and stuff
        with boa.env.prank(admin):
            gauge_controller.add_type("crvUSD Market")
            gauge_controller.change_type_weight(0, 10 ** 18)
            gauge_controller.add_gauge(boosted_lm_callback.address, 0, 10 ** 18)

        integral = 0  # ∫(balance * rate(t) / totalSupply(t) dt)
        checkpoint = boa.env.vm.patch.timestamp
        checkpoint_rate = crv.rate()
        checkpoint_supply = 0
        checkpoint_balance = 0

        boa.env.time_travel(seconds=WEEK)

        # Let Alice and Bob have about the same collateral token amount
        with boa.env.prank(admin):
            collateral_token._mint_for_testing(alice, 1000 * 10**18)
            collateral_token._mint_for_testing(bob, 1000 * 10**18)

        # Chad creates loan just to get crvUSD
        collateral_token._mint_for_testing(chad, 10**26, sender=admin)
        market_controller.create_loan(10 ** 25, 10 ** 24, 10, sender=chad)

        def update_integral():
            nonlocal checkpoint, checkpoint_rate, integral, checkpoint_balance, checkpoint_supply

            t1 = boa.env.vm.patch.timestamp
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
            checkpoint_supply = collateral_token.balanceOf(market_amm) - market_amm.admin_fees_y()
            checkpoint_balance = market_amm.get_sum_xy(alice)[1]

        def chad_trading(p_target):
            bob_bands = market_amm.read_user_tick_numbers(bob)
            bob_bands = list(range(bob_bands[0], bob_bands[1] + 1))
            alice_bands = market_amm.read_user_tick_numbers(alice)
            alice_bands = list(range(alice_bands[0], alice_bands[1] + 1))
            print("Bob bands:", bob_bands)
            print("Alice bands:", alice_bands)
            print("Active band:", market_amm.active_band())
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

        def check():
            if random() < 0.5:
                boosted_lm_callback.user_checkpoint(alice, sender=alice)
            if random() < 0.5:
                boosted_lm_callback.user_checkpoint(bob, sender=bob)

            dt = randrange(1, YEAR // 20)
            boa.env.time_travel(seconds=dt)

            total_collateral_from_amm = collateral_token.balanceOf(market_amm) - market_amm.admin_fees_y() - 10 ** 25
            total_collateral_from_lm_cb = boosted_lm_callback.total_collateral() - 10 ** 25
            working_collateral_from_lm_cb = boosted_lm_callback.working_supply() - 10 ** 25 * 4 // 10
            print("Total collateral:", total_collateral_from_amm, total_collateral_from_lm_cb)
            print("Working collateral:", total_collateral_from_amm * 4 // 10, working_collateral_from_lm_cb)
            if total_collateral_from_amm > 0 and total_collateral_from_lm_cb > 0:
                assert approx(total_collateral_from_amm, total_collateral_from_lm_cb, 1e-14)
                assert approx(total_collateral_from_amm * 4 // 10, working_collateral_from_lm_cb, 1e-14)

            boosted_lm_callback.user_checkpoint(alice, sender=alice)
            update_integral()
            print(dt / 86400, integral, boosted_lm_callback.integrate_fraction(alice), "\n")
            assert approx(boosted_lm_callback.integrate_fraction(alice), integral, 1e-14)

        def deposit_and_borrow(user, collateral_amt, borrow_amt):
            with boa.env.prank(user):
                collateral_token.approve(market_controller.address, collateral_amt)
                if market_controller.loan_exists(alice):
                    market_controller.borrow_more(collateral_amt, borrow_amt)
                else:
                    market_controller.create_loan(collateral_amt, borrow_amt, 10)
                name = "Alice" if user == alice else "Bob"
                print(f"{name} deposits:", collateral_amt, borrow_amt)
                update_integral()

        def repay_and_withdraw(user, repay_amount, withdraw_amount=0):
            with boa.env.prank(user):
                name = "Alice" if user == alice else "Bob"
                market_controller.repay(repay_amount)
                print(f"{name} repays:", repay_amount)
                if withdraw_amount > 0:
                    market_controller.remove_collateral(withdraw_amount)
                    print(f"{name} withdraws:", withdraw_amount)

        dt = randrange(1, YEAR // 5)
        boa.env.time_travel(seconds=dt)

        deposit_and_borrow(bob, 21516952233769625863, 6617957748829691314176)
        chad_trading(328705202042361937920)
        update_integral()
        check()

        dt = randrange(1, YEAR // 5)
        boa.env.time_travel(seconds=dt)

        deposit_and_borrow(alice, 61646012523713269734, 12933246193085710336000)
        chad_trading(229391384210005229568)
        update_integral()
        check()

        dt = randrange(1, YEAR // 5)
        boa.env.time_travel(seconds=dt)

        for p in [220473872075276386304, 311843393564942860288, 222328259864778145792, 314589246863500509184]:
            chad_trading(p)
            update_integral()
            check()

            dt = randrange(1, YEAR // 5)
            boa.env.time_travel(seconds=dt)

        repay_and_withdraw(alice, 11154780410093718470656, 25869130582301525676)
        chad_trading(295175878205382721536)
        update_integral()
        check()

        for p in [293031169357270646784]:
            chad_trading(p)
            update_integral()
            check()

            dt = randrange(1, YEAR // 5)
            boa.env.time_travel(seconds=dt)

        repay_and_withdraw(alice, 1497963292007708753920)
        chad_trading(309410174297774882816)
        update_integral()
        check()

        for p in [286549586472273608704, 331613449847548215296]:
            chad_trading(p)
            update_integral()
            check()

            dt = randrange(1, YEAR // 5)
            boa.env.time_travel(seconds=dt)

        deposit_and_borrow(alice, 8329553966053150194, 481158074118051201024)
        chad_trading(66144411435842985984)
        update_integral()
        check()

        dt = randrange(1, YEAR // 5)
        boa.env.time_travel(seconds=dt)

        deposit_and_borrow(alice, 64317789720266774874, 1761073001883652325376)
        chad_trading(329383596357752520704)
        update_integral()
        check()

        for p in [34600421933964500992, 324467599330016624640]:
            chad_trading(p)
            update_integral()
            check()

            dt = randrange(1, YEAR // 5)
            boa.env.time_travel(seconds=dt)

        repay_and_withdraw(bob, 3157152627407787130880)
        chad_trading(33342661200807497728)
        update_integral()
        check()

        dt = randrange(1, YEAR // 5)
        boa.env.time_travel(seconds=dt)

        deposit_and_borrow(alice, 27148857638579652401, 355494092019161956352)
        chad_trading(28760555323610148864)
        update_integral()
        check()

        for p in [322423700767300845568, 29828569335522738176, 30265632017537286144, 30184027540448387072, 327572615074833170432, 28689861843333869568]:
            chad_trading(p)
            update_integral()
            check()

            dt = YEAR // 5
            boa.env.time_travel(seconds=dt)

        repay_and_withdraw(alice, 2711870065242579927040)
        chad_trading(28091716187954302976)
        update_integral()
        check()

    raise Exception("Success")
