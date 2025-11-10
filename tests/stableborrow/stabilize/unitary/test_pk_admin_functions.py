import boa

from tests.utils.constants import ZERO_ADDRESS

ADMIN_ACTIONS_DEADLINE = 3 * 86400


def test_parameters(peg_keepers, swaps, stablecoin, admin, reg):
    for peg_keeper, swap in zip(peg_keepers, swaps):
        assert peg_keeper.pegged() == stablecoin.address
        assert peg_keeper.pool() == swap.address

        assert peg_keeper.admin() == admin
        assert peg_keeper.future_admin() == ZERO_ADDRESS

        assert peg_keeper.caller_share() == 2 * 10**4
        assert peg_keeper.regulator() == reg.address


def test_update_access(
    peg_keepers,
    peg_keeper_updater,
    add_initial_liquidity,
    provide_token_to_peg_keepers,
    imbalance_pools,
):
    imbalance_pools(1)
    with boa.env.prank(peg_keeper_updater):
        for pk in peg_keepers:
            pk.update()


def test_set_new_caller_share(peg_keepers, admin):
    new_caller_share = 5 * 10**4
    with boa.env.prank(admin):
        for pk in peg_keepers:
            pk.set_new_caller_share(new_caller_share)
            assert pk.caller_share() == new_caller_share


def test_set_new_caller_share_bad_value(peg_keepers, admin):
    with boa.env.prank(admin):
        for pk in peg_keepers:
            with boa.reverts():  # dev: bad part value
                pk.set_new_caller_share(10**5 + 1)


def test_set_new_caller_share_only_admin(peg_keepers, alice):
    with boa.env.prank(alice):
        for pk in peg_keepers:
            with boa.reverts():  # dev: only admin
                pk.set_new_caller_share(5 * 10**4)


def test_set_new_regulator(peg_keepers, admin, alice, bob):
    new_regulator = bob
    for pk in peg_keepers:
        with boa.env.prank(alice):
            with boa.reverts():  # dev: only admin
                pk.set_new_regulator(new_regulator)
        with boa.env.prank(admin):
            pk.set_new_regulator(new_regulator)
            assert pk.regulator() == new_regulator
            with boa.reverts():  # dev: zero address
                pk.set_new_regulator(ZERO_ADDRESS)


def test_new_admin(peg_keepers, admin, alice, bob):
    for pk in peg_keepers:
        # commit_new_admin
        with boa.env.prank(alice):
            with boa.reverts():  # dev: only admin
                pk.commit_new_admin(alice)
        with boa.env.prank(admin):
            pk.commit_new_admin(alice)

        assert pk.admin() == admin
        assert pk.future_admin() == alice
        assert boa.env.timestamp + ADMIN_ACTIONS_DEADLINE == pk.new_admin_deadline()

        # apply_new_admin
        boa.env.time_travel(ADMIN_ACTIONS_DEADLINE - 60)
        with boa.reverts():  # dev: insufficient time
            with boa.env.prank(alice):
                pk.apply_new_admin()

        boa.env.time_travel(60)
        with boa.reverts():  # dev: only new admin
            with boa.env.prank(bob):
                pk.apply_new_admin()
        with boa.env.prank(alice):
            pk.apply_new_admin()

        with boa.reverts():  # dev: no active action
            with boa.env.prank(alice):
                pk.apply_new_admin()

        assert pk.admin() == alice
        assert pk.future_admin() == alice
        assert pk.new_admin_deadline() == 0


def test_revert_new_admin(peg_keepers, admin, alice):
    for pk in peg_keepers:
        with boa.env.prank(admin):
            pk.commit_new_admin(alice)
            pk.commit_new_admin(admin)
        assert pk.future_admin() == admin
