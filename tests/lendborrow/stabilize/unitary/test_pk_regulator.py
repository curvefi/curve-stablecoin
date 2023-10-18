import boa


ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ADMIN_ACTIONS_DEADLINE = 3 * 86400


def test_price_range(peg_keepers, swaps, stablecoin, admin, receiver, reg):
    with boa.env.prank(admin):
        reg.set_price_deviation(10 ** 17)

    for peg_keeper, swap in zip(peg_keepers, swaps):
        assert reg.provide_allowed(peg_keeper)
        assert reg.withdraw_allowed(peg_keeper)

        # Move current price (get_p) a little
        swap.eval("self.rate_multipliers[0] *= 2")
        assert reg.provide_allowed(peg_keeper)
        assert reg.withdraw_allowed(peg_keeper)

        # Move further
        swap.eval("self.rate_multipliers[0] *= 5")

        assert not reg.provide_allowed(peg_keeper)
        assert not reg.withdraw_allowed(peg_keeper)


def test_price_order(peg_keepers, mock_price_pairs, swaps, initial_amounts, stablecoin, admin, alice, mint_alice, reg, agg):
    with boa.env.prank(admin):
        reg.remove_price_pairs([mock.address for mock in mock_price_pairs])

    # note: assuming swaps' prices are close enough
    for i, (peg_keeper, swap, (initial_amount, _)) in enumerate(zip(peg_keepers, swaps, initial_amounts)):
        with boa.env.anchor():
            with boa.env.prank(admin):
                # Price change break aggregator.price() check
                agg.remove_price_pair(i)

            with boa.env.prank(alice):
                amount = 7 * initial_amount // 1000  # Just in
                # Make sure small decline still works
                swap.exchange(0, 1, amount, 0)
                boa.env.time_travel(seconds=6000)  # Update EMA
                assert reg.provide_allowed(peg_keeper)
                assert reg.withdraw_allowed(peg_keeper)  # no such check for withdraw

                # and a bigger one
                swap.exchange(0, 1, amount, 0)
                boa.env.time_travel(seconds=6000)  # Update EMA
                assert not reg.provide_allowed(peg_keeper)
                assert reg.withdraw_allowed(peg_keeper)


def test_aggregator_price(peg_keepers, mock_price_pairs, reg, agg, admin, stablecoin):
    mock_pair = boa.load('contracts/testing/MockPricePair.vy', 10 ** 18, stablecoin)
    with boa.env.prank(admin):
        agg.add_price_pair(mock_pair)
        for price in [0.95, 1.05]:
            mock_pair.set_price(int(price * 10 ** 18))
            boa.env.time_travel(seconds=50000)
            for peg_keeper in peg_keepers:
                assert reg.provide_allowed(peg_keeper) == (price > 1)
                assert reg.withdraw_allowed(peg_keeper) == (price < 1)


def test_set_killed(reg, peg_keepers, admin):
    peg_keeper = peg_keepers[0]
    with boa.env.prank(admin):
        assert reg.is_killed() == 0

        assert reg.provide_allowed(peg_keeper)
        assert reg.withdraw_allowed(peg_keeper)

        reg.set_killed(1)
        assert reg.is_killed() == 1

        assert not reg.provide_allowed(peg_keeper)
        assert reg.withdraw_allowed(peg_keeper)

        reg.set_killed(2)
        assert reg.is_killed() == 2

        assert reg.provide_allowed(peg_keeper)
        assert not reg.withdraw_allowed(peg_keeper)

        reg.set_killed(3)
        assert reg.is_killed() == 3

        assert not reg.provide_allowed(peg_keeper)
        assert not reg.withdraw_allowed(peg_keeper)


def test_admin(reg, admin, alice):
    # initial parameters
    assert reg.price_deviation() == 100 * 10 ** 18
    assert reg.emergency_admin() == admin
    assert reg.is_killed() == 0
    assert reg.admin() == admin

    # third party has no access
    with boa.env.prank(alice):
        with boa.reverts():
            reg.set_price_deviation(10 ** 17)
        with boa.reverts():
            reg.set_emergency_admin(alice)
        with boa.reverts():
            reg.set_killed(1)
        with boa.reverts():
            reg.set_admin(alice)

    # admin has access
    with boa.env.prank(admin):
        reg.set_price_deviation(10 ** 17)
        assert reg.price_deviation() == 10 ** 17

        reg.set_emergency_admin(alice)
        assert reg.emergency_admin() == alice

        reg.set_killed(1)
        assert reg.is_killed() == 1
        with boa.env.prank(alice):  # emergency admin
            reg.set_killed(2)
            assert reg.is_killed() == 2

        reg.set_admin(alice)
        assert reg.admin() == alice
