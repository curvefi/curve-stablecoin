import boa
import pytest
from random import random, randrange, choice
from tests.utils.constants import MAX_UINT256

YEAR = 365 * 86400
WEEK = 7 * 86400


def test_simple_exchange(
    admin,
    trader,
    collateral_token,
    crv,
    controller,
    amm,
    lm_callback,
    minter,
):
    borrower1 = boa.env.generate_address("borrower1")
    borrower2 = boa.env.generate_address("borrower2")
    for b in (borrower1, borrower2):
        boa.deal(collateral_token, b, 1000 * 10**18)
        collateral_token.approve(controller, MAX_UINT256, sender=b)

    boa.env.time_travel(seconds=2 * WEEK + 5)

    controller.create_loan(10**21, 10**21 * 2600, 10, sender=borrower1)
    controller.create_loan(10**21, 10**21 * 1000, 10, sender=borrower2)

    # Time travel and checkpoint
    boa.env.time_travel(4 * WEEK)
    lm_callback.user_checkpoint(borrower1, sender=borrower1)
    lm_callback.user_checkpoint(borrower2, sender=borrower2)

    rewards_borrower1 = lm_callback.integrate_fraction(borrower1)
    rewards_borrower2 = lm_callback.integrate_fraction(borrower2)
    assert rewards_borrower1 == rewards_borrower2

    # Trader buys crvUSD --> collateral and takes a half of borrower1's deposit
    amm.exchange_dy(0, 1, 10**21 // 2, 2**255, sender=trader)

    # Time travel and checkpoint
    boa.env.time_travel(4 * WEEK)
    lm_callback.user_checkpoint(borrower1, sender=borrower1)
    lm_callback.user_checkpoint(borrower2, sender=borrower2)
    old_rewards_borrower1 = rewards_borrower1
    old_rewards_borrower2 = rewards_borrower2

    # borrower2 earned 2 times more CRV
    rewards_borrower1 = lm_callback.integrate_fraction(borrower1)
    rewards_borrower2 = lm_callback.integrate_fraction(borrower2)
    d_borrower1 = rewards_borrower1 - old_rewards_borrower1
    d_borrower2 = rewards_borrower2 - old_rewards_borrower2
    assert d_borrower2 / d_borrower1 == pytest.approx(2, rel=1e-15)

    minter.mint(lm_callback.address, sender=borrower1)
    assert crv.balanceOf(borrower1) == rewards_borrower1

    minter.mint(lm_callback.address, sender=borrower2)
    assert crv.balanceOf(borrower2) == rewards_borrower2


def test_gauge_integral_with_exchanges(
    admin,
    trader,
    collateral_token,
    borrowed_token,
    crv,
    lm_callback,
    controller,
    amm,
    price_oracle,
    minter,
):
    with boa.env.anchor():
        borrower1 = boa.env.generate_address("borrower1")
        borrower2 = boa.env.generate_address("borrower2")
        for b in (borrower1, borrower2):
            boa.deal(collateral_token, b, 1000 * 10**18)
            collateral_token.approve(controller, MAX_UINT256, sender=b)
            borrowed_token.approve(controller, MAX_UINT256, sender=b)

        integral = 0  # ∫(balance * rate(t) / totalSupply(t) dt)
        checkpoint = boa.env.timestamp
        checkpoint_rate = crv.rate()
        checkpoint_supply = 0
        checkpoint_balance = 0

        boa.env.time_travel(seconds=WEEK)

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
            checkpoint_supply = collateral_token.balanceOf(amm)
            checkpoint_balance = amm.get_sum_xy(borrower1)[1]

        # borrower2 always deposits or withdraws; borrower1 does so more rarely
        for i in range(40):
            is_borrower1 = random() < 0.2
            dt = randrange(1, YEAR // 5)
            boa.env.time_travel(seconds=dt)
            print("Time travel", dt)

            with boa.env.prank(borrower2):
                (
                    collateral_in_amm_borrower2,
                    stablecoin_in_amm_borrower2,
                    debt_borrower2,
                    __,
                ) = controller.user_state(borrower2)
                is_withdraw_borrower2 = (collateral_in_amm_borrower2 > 0) * (
                    random() < 0.5
                )
                is_underwater_borrower2 = stablecoin_in_amm_borrower2 > 0

                if is_withdraw_borrower2:
                    amount_borrower2 = randrange(1, collateral_in_amm_borrower2 + 1)
                    if amount_borrower2 == collateral_in_amm_borrower2:
                        print("borrower2 repays (full):", debt_borrower2)
                        print("borrower2 withdraws (full):", amount_borrower2)
                        controller.repay(debt_borrower2)
                        assert amm.get_sum_xy(borrower2)[1] == pytest.approx(
                            lm_callback.user_collateral(borrower2), rel=1e-13
                        )
                    elif controller.health(borrower2) > 0:
                        repay_amount_borrower2 = int(
                            debt_borrower2 // 10
                            + (debt_borrower2 * 9 // 10) * random() * 0.99
                        )
                        print("borrower2 repays:", repay_amount_borrower2)
                        controller.repay(repay_amount_borrower2)
                        if not is_underwater_borrower2:
                            min_collateral_required_borrower2 = (
                                controller.min_collateral(
                                    debt_borrower2 - repay_amount_borrower2, 10
                                )
                            )
                            remove_amount_borrower2 = min(
                                collateral_in_amm_borrower2
                                - min_collateral_required_borrower2,
                                amount_borrower2,
                            )
                            remove_amount_borrower2 = max(remove_amount_borrower2, 0)
                            if remove_amount_borrower2 > 0:
                                print("borrower2 withdraws:", remove_amount_borrower2)
                                controller.remove_collateral(remove_amount_borrower2)
                            assert amm.get_sum_xy(borrower2)[1] == pytest.approx(
                                lm_callback.user_collateral(borrower2), rel=1e-13
                            )
                    update_integral()
                elif not is_underwater_borrower2:
                    amount_borrower2 = randrange(
                        1, collateral_token.balanceOf(borrower2) // 10 + 1
                    )
                    max_borrowable_borrower2 = controller.max_borrowable(
                        amount_borrower2, 10, borrower2
                    )
                    borrow_amount_borrower2 = min(
                        int(random() * max_borrowable_borrower2),
                        max_borrowable_borrower2,
                    )
                    if borrow_amount_borrower2 > 0:
                        print(
                            "borrower2 deposits:",
                            amount_borrower2,
                            borrow_amount_borrower2,
                        )
                        if controller.loan_exists(borrower2):
                            controller.borrow_more(
                                amount_borrower2, borrow_amount_borrower2
                            )
                        else:
                            controller.create_loan(
                                amount_borrower2, borrow_amount_borrower2, 10
                            )
                        update_integral()
                    assert amm.get_sum_xy(borrower2)[1] == pytest.approx(
                        lm_callback.user_collateral(borrower2), rel=1e-13
                    )

            if is_borrower1:
                with boa.env.prank(borrower1):
                    (
                        collateral_in_amm_borrower1,
                        stablecoin_in_amm_borrower1,
                        debt_borrower1,
                        __,
                    ) = controller.user_state(borrower1)
                    is_withdraw_borrower1 = (collateral_in_amm_borrower1 > 0) * (
                        random() < 0.5
                    )
                    is_underwater_borrower1 = stablecoin_in_amm_borrower1 > 0

                    if is_withdraw_borrower1:
                        amount_borrower1 = randrange(1, collateral_in_amm_borrower1 + 1)
                        if amount_borrower1 == collateral_in_amm_borrower1:
                            print("borrower1 repays (full):", debt_borrower1)
                            print("borrower1 withdraws (full):", amount_borrower1)
                            controller.repay(debt_borrower1)
                            assert amm.get_sum_xy(borrower1)[1] == pytest.approx(
                                lm_callback.user_collateral(borrower1), rel=1e-13
                            )
                        elif controller.health(borrower1) > 0:
                            repay_amount_borrower1 = int(
                                debt_borrower1 // 10
                                + (debt_borrower1 * 9 // 10) * random() * 0.99
                            )
                            print("borrower1 repays:", repay_amount_borrower1)
                            controller.repay(repay_amount_borrower1)
                            if not is_underwater_borrower1:
                                min_collateral_required_borrower1 = (
                                    controller.min_collateral(
                                        debt_borrower1 - repay_amount_borrower1, 10
                                    )
                                )
                                remove_amount_borrower1 = min(
                                    collateral_in_amm_borrower1
                                    - min_collateral_required_borrower1,
                                    amount_borrower1,
                                )
                                remove_amount_borrower1 = max(
                                    remove_amount_borrower1, 0
                                )
                                if remove_amount_borrower1 > 0:
                                    print(
                                        "borrower1 withdraws:", remove_amount_borrower1
                                    )
                                    controller.remove_collateral(
                                        remove_amount_borrower1
                                    )
                            assert amm.get_sum_xy(borrower1)[1] == pytest.approx(
                                lm_callback.user_collateral(borrower1), rel=1e-13
                            )
                        update_integral()
                    elif not is_underwater_borrower1:
                        amount_borrower1 = randrange(
                            1, collateral_token.balanceOf(borrower1) // 10 + 1
                        )
                        max_borrowable_borrower1 = controller.max_borrowable(
                            amount_borrower1, 10, borrower1
                        )
                        borrow_amount_borrower1 = min(
                            int(random() * max_borrowable_borrower1),
                            max_borrowable_borrower1,
                        )
                        if borrow_amount_borrower1 > 0:
                            print(
                                "borrower1 deposits:",
                                amount_borrower1,
                                borrow_amount_borrower1,
                            )
                            if controller.loan_exists(borrower1):
                                controller.borrow_more(
                                    amount_borrower1, borrow_amount_borrower1
                                )
                            else:
                                controller.create_loan(
                                    amount_borrower1, borrow_amount_borrower1, 10
                                )
                            update_integral()
                        assert amm.get_sum_xy(borrower1)[1] == pytest.approx(
                            lm_callback.user_collateral(borrower1), rel=1e-13
                        )

            # Trader swaps
            borrower1_bands = amm.read_user_tick_numbers(borrower1)
            borrower1_bands = (
                []
                if borrower1_bands[0] == borrower1_bands[1]
                else list(range(borrower1_bands[0], borrower1_bands[1] + 1))
            )
            borrower2_bands = amm.read_user_tick_numbers(borrower2)
            borrower2_bands = (
                []
                if borrower2_bands[0] == borrower2_bands[1]
                else list(range(borrower2_bands[0], borrower2_bands[1] + 1))
            )
            available_bands = borrower1_bands + borrower2_bands
            print("borrower2 bands:", borrower2_bands)
            print("borrower1 bands:", borrower1_bands)
            print("Active band:", amm.active_band())
            p_o = amm.price_oracle()
            upper_bands = sorted(
                list(
                    filter(
                        lambda band: amm.p_oracle_down(band) > p_o,
                        available_bands,
                    )
                )
            )[-5:]
            lower_bands = sorted(
                list(filter(lambda band: amm.p_oracle_up(band) < p_o, available_bands))
            )[:5]
            available_bands = upper_bands + lower_bands
            if len(available_bands) > 0:
                target_band = choice(available_bands)
                p_up = amm.p_oracle_up(target_band)
                p_down = amm.p_oracle_down(target_band)
                p_target = int(p_down + random() * (p_up - p_down))
                price_oracle.set_price(p_target, sender=admin)
                print("Price set to:", p_target)
                amount, pump = amm.get_amount_for_price(p_target)
                with boa.env.prank(trader):
                    if pump:
                        amm.exchange(0, 1, amount, 0)
                    else:
                        amm.exchange(1, 0, amount, 0)
                print("Swap:", amount, pump)
                print("Active band:", amm.active_band())
                update_integral()

            # Checking that updating the checkpoint in the same second does nothing
            # Also everyone can update: that should make no difference, too
            if random() < 0.5:
                lm_callback.user_checkpoint(borrower1, sender=borrower1)
            if random() < 0.5:
                lm_callback.user_checkpoint(borrower2, sender=borrower2)

            dt = randrange(1, YEAR // 20)
            boa.env.time_travel(seconds=dt)
            print("Time travel", dt)

            total_collateral_from_amm = collateral_token.balanceOf(amm)
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

            with boa.env.prank(borrower1):
                crv_balance = crv.balanceOf(borrower1)
                with boa.env.anchor():
                    crv_reward = lm_callback.claimable_tokens(borrower1)
                minter.mint(lm_callback.address)
                assert crv.balanceOf(borrower1) - crv_balance == crv_reward

                update_integral()
                print(
                    i, dt / 86400, integral, lm_callback.integrate_fraction(borrower1)
                )
                assert lm_callback.integrate_fraction(borrower1) == pytest.approx(
                    integral, rel=1e-14
                )

            with boa.env.prank(borrower2):
                crv_balance = crv.balanceOf(borrower2)
                with boa.env.anchor():
                    crv_reward = lm_callback.claimable_tokens(borrower2)
                minter.mint(lm_callback.address)
                assert crv.balanceOf(borrower2) - crv_balance == crv_reward


def test_full_repay_underwater(
    admin,
    trader,
    collateral_token,
    borrowed_token,
    crv,
    lm_callback,
    controller,
    amm,
    price_oracle,
    minter,
):
    with boa.env.anchor():
        borrower1 = boa.env.generate_address("borrower1")
        borrower2 = boa.env.generate_address("borrower2")
        for b in (borrower1, borrower2):
            boa.deal(collateral_token, b, 1000 * 10**18)
            collateral_token.approve(controller, MAX_UINT256, sender=b)
            borrowed_token.approve(controller, MAX_UINT256, sender=b)

        dt = randrange(1, YEAR // 5)
        boa.env.time_travel(seconds=dt)

        # borrower2 creates a high-LTV loan (will go underwater after trade)
        with boa.env.prank(borrower2):
            amount_borrower2 = 10**20
            controller.create_loan(amount_borrower2, int(amount_borrower2 * 2000), 10)
            print("borrower2 deposits:", amount_borrower2)

        # borrower1 creates a conservative loan (stays above water)
        with boa.env.prank(borrower1):
            amount_borrower1 = 10**20
            controller.create_loan(amount_borrower1, int(amount_borrower1 * 500), 10)
            print("borrower1 deposits:", amount_borrower1)

        print(collateral_token.balanceOf(amm), lm_callback.total_collateral())

        dt = randrange(1, YEAR // 5)
        boa.env.time_travel(seconds=dt)

        # Trader pushes price so borrower2 goes underwater
        borrower2_bands = amm.read_user_tick_numbers(borrower2)
        borrower2_bands = list(range(borrower2_bands[0], borrower2_bands[1] + 1))
        print("borrower2 bands:", borrower2_bands)
        print("Active band:", amm.active_band())
        target_band = borrower2_bands[7]
        p_up = amm.p_oracle_up(target_band)
        p_down = amm.p_oracle_down(target_band)
        p_target = int((p_down + p_up) / 2)
        price_oracle.set_price(p_target, sender=admin)
        print("Price set to:", p_target)
        amount, pump = amm.get_amount_for_price(p_target)
        with boa.env.prank(trader):
            if pump:
                amm.exchange(0, 1, amount, 0)
            else:
                amm.exchange(1, 0, amount, 0)
        print("Swap:", amount, pump, "\n")
        print("Active band:", amm.active_band())

        # borrower2 fully repays while underwater
        debt_borrower2 = controller.user_state(borrower2)[2]
        controller.repay(debt_borrower2, sender=borrower2)
        print("borrower2 repays (full):", debt_borrower2)
        print("borrower2 withdraws (full):", amount_borrower2)

        total_collateral_from_amm = collateral_token.balanceOf(amm)
        total_collateral_from_lm_cb = lm_callback.total_collateral()
        print(
            "Total collateral:", total_collateral_from_amm, total_collateral_from_lm_cb
        )
        assert total_collateral_from_amm == pytest.approx(
            total_collateral_from_lm_cb, rel=1e-15
        )

        for user in (borrower1, borrower2):
            with boa.env.prank(user):
                crv_balance = crv.balanceOf(user)
                with boa.env.anchor():
                    crv_reward = lm_callback.claimable_tokens(borrower2)
                minter.mint(lm_callback.address)
                assert crv.balanceOf(user) - crv_balance == crv_reward
