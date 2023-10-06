import boa


ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ADMIN_ACTIONS_DEADLINE = 3 * 86400


def test_price_range(peg_keepers, swaps, stablecoin, admin, receiver, reg):
    with boa.env.prank(admin):
        reg.set_price_deviation(10 ** 17)

    for peg_keeper, swap in zip(peg_keepers, swaps):
        assert reg.provide_allowed(peg_keeper)
        assert reg.withdraw_allowed(peg_keeper)

        # Move current price (get_p)
        swap.eval("self.rate_multipliers[0] *= 10")

        assert not reg.provide_allowed(peg_keeper)
        assert not reg.withdraw_allowed(peg_keeper)


def test_price_order(peg_keepers, mock_price_pairs, swaps, stablecoin, admin, receiver, reg):
    with boa.env.prank(admin):
        for price_pair in mock_price_pairs:
            reg.remove_price_pair(price_pair)

    for peg_keeper, swap in zip(peg_keepers, swaps):
        # note: assuming swaps' prices are close enough
        # Make sure big price works
        rate_mul_mul = 2
        swap.eval(f"self.rate_multipliers[0] *= {rate_mul_mul}")
        assert reg.provide_allowed(peg_keeper)
        assert not reg.withdraw_allowed(peg_keeper)

        # and small one
        swap.eval(f"self.rate_multipliers[0] /= {rate_mul_mul ** 2}")

        assert not reg.provide_allowed(peg_keeper)
        assert reg.withdraw_allowed(peg_keeper)

        # Return to initial
        swap.eval(f"self.rate_multipliers[0] *= {rate_mul_mul}")


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
    assert reg.price_deviation() == 1000 * 10 ** 18
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
