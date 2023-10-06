import pytest
import boa


ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ADMIN_ACTIONS_DEADLINE = 3 * 86400


def test_parameters(peg_keepers, swaps, stablecoin, admin, receiver, reg):
    for peg_keeper, swap in zip(peg_keepers, swaps):
        assert peg_keeper.pegged() == stablecoin.address
        assert peg_keeper.pool() == swap.address

        assert peg_keeper.admin() == admin
        assert peg_keeper.future_admin() == ZERO_ADDRESS

        assert peg_keeper.receiver() == receiver
        assert peg_keeper.future_receiver() == ZERO_ADDRESS

        assert peg_keeper.caller_share() == 2 * 10**4
        assert peg_keeper.regulator() == reg.address


def test_update_access(peg_keepers, peg_keeper_updater,
                       add_initial_liquidity,
                       provide_token_to_peg_keepers,
                       imbalance_pools):
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


def test_set_new_regulator(peg_keepers, admin):
    new_regulator = ZERO_ADDRESS
    with boa.env.prank(admin):
        for pk in peg_keepers:
            pk.set_new_regulator(new_regulator)
            assert pk.regulator() == new_regulator


def test_set_new_regulator_only_admin(peg_keepers, alice):
    with boa.env.prank(alice):
        for pk in peg_keepers:
            with boa.reverts():  # dev: only admin
                pk.set_new_regulator(ZERO_ADDRESS)


def test_commit_new_admin(peg_keepers, admin, alice):
    with boa.env.prank(admin):
        for pk in peg_keepers:
            pk.commit_new_admin(alice)

            assert pk.admin() == admin
            assert pk.future_admin() == alice
            assert boa.env.vm.patch.timestamp + ADMIN_ACTIONS_DEADLINE == pk.new_admin_deadline()


def test_commit_new_admin_access(peg_keepers, alice):
    with boa.env.prank(alice):
        for pk in peg_keepers:
            with boa.reverts():  # dev: only admin
                pk.commit_new_admin(alice)


def test_apply_new_admin(peg_keepers, admin, alice):
    for pk in peg_keepers:
        with boa.env.prank(admin):
            pk.commit_new_admin(alice)
        boa.env.time_travel(ADMIN_ACTIONS_DEADLINE)
        with boa.env.prank(alice):
            pk.apply_new_admin()

        assert pk.admin() == alice
        assert pk.future_admin() == alice
        assert pk.new_admin_deadline() == 0


def test_apply_new_admin_only_new_admin(peg_keepers, admin, alice, bob):
    for pk in peg_keepers:
        with boa.env.prank(admin):
            pk.commit_new_admin(alice)
        boa.env.time_travel(ADMIN_ACTIONS_DEADLINE)

        with boa.reverts():  # dev: only new admin
            with boa.env.prank(bob):
                pk.apply_new_admin()


def test_apply_new_admin_deadline(peg_keepers, admin, alice):
    for pk in peg_keepers:
        with boa.env.prank(admin):
            pk.commit_new_admin(alice)
        boa.env.time_travel(ADMIN_ACTIONS_DEADLINE - 60)
        with boa.reverts():  # dev: insufficient time
            with boa.env.prank(alice):
                pk.apply_new_admin()


def test_apply_new_admin_no_active(peg_keepers, admin, alice):
    for pk in peg_keepers:
        with boa.env.prank(admin):
            pk.commit_new_admin(alice)
        boa.env.time_travel(ADMIN_ACTIONS_DEADLINE)
        with boa.env.prank(alice):
            pk.apply_new_admin()

        with boa.reverts():  # dev: no active action
            with boa.env.prank(alice):
                pk.apply_new_admin()


def test_revert_new_admin(peg_keepers, admin, alice):
    for pk in peg_keepers:
        with boa.env.prank(admin):
            pk.commit_new_admin(alice)
            pk.revert_new_options()
        assert pk.new_admin_deadline() == 0


def test_revert_new_admin_only_admin(peg_keepers, admin, alice):
    for pk in peg_keepers:
        with boa.env.prank(admin):
            pk.commit_new_admin(alice)
            with boa.reverts():  # dev: only admin
                with boa.env.prank(alice):
                    pk.revert_new_options()


def test_revert_new_admin_without_commit(peg_keepers, admin):
    for pk in peg_keepers:
        with boa.env.prank(admin):
            pk.revert_new_options()
        assert pk.new_receiver_deadline() == 0


def test_commit_new_receiver(peg_keepers, admin, alice, receiver):
    for pk in peg_keepers:
        with boa.env.prank(admin):
            pk.commit_new_receiver(alice)

        assert pk.receiver() == receiver
        assert pk.future_receiver() == alice
        assert boa.env.vm.patch.timestamp + ADMIN_ACTIONS_DEADLINE == pk.new_receiver_deadline()


def test_commit_new_receiver_access(peg_keepers, alice):
    for pk in peg_keepers:
        with boa.reverts():  # dev: only admin
            with boa.env.prank(alice):
                pk.commit_new_receiver(alice)


def test_apply_new_receiver(peg_keepers, admin, alice):
    for pk in peg_keepers:
        with boa.env.prank(admin):
            pk.commit_new_receiver(alice)
            boa.env.time_travel(ADMIN_ACTIONS_DEADLINE)
            pk.apply_new_receiver()

        assert pk.receiver() == alice
        assert pk.future_receiver() == alice


def test_apply_new_receiver_deadline(peg_keepers, admin, alice):
    for pk in peg_keepers:
        with boa.env.prank(admin):
            pk.commit_new_receiver(alice)
            boa.env.time_travel(ADMIN_ACTIONS_DEADLINE - 60)
            with boa.reverts():  # dev: insufficient time
                pk.apply_new_receiver()


def test_apply_new_receiver_no_active(peg_keepers, alice):
    for pk in peg_keepers:
        with boa.env.prank(alice):
            with boa.reverts():  # dev: no active action
                pk.apply_new_receiver()


def test_revert_new_receiver(peg_keepers, admin, alice):
    for pk in peg_keepers:
        with boa.env.prank(admin):
            pk.commit_new_receiver(alice)
            pk.revert_new_options()
            assert pk.new_receiver_deadline() == 0


def test_revert_new_receiver_only_admin(peg_keepers, admin, alice):
    for pk in peg_keepers:
        with boa.env.prank(admin):
            pk.commit_new_receiver(alice)
        with boa.reverts():  # dev: only admin
            with boa.env.prank(alice):
                pk.revert_new_options()


def test_revert_new_receiver_without_commit(peg_keepers, admin):
    for pk in peg_keepers:
        with boa.env.prank(admin):
            pk.revert_new_options()
        assert pk.new_receiver_deadline() == 0


@pytest.mark.parametrize("action0", ["commit_new_admin", "commit_new_receiver"])
@pytest.mark.parametrize("action1", ["commit_new_admin", "commit_new_receiver"])
def test_commit_already_active(peg_keepers, admin, alice, action0, action1):
    with boa.env.prank(admin):
        for pk in peg_keepers:
            if action0 == "commit_new_admin":
                pk.commit_new_admin(alice)
            else:
                pk.commit_new_receiver(alice)

            if action1 == "commit_new_admin":
                if action0 != action1:
                    pk.commit_new_admin(alice)
                else:
                    with boa.reverts():  # dev: active action
                        pk.commit_new_admin(alice)
            else:
                if action0 != action1:
                    pk.commit_new_receiver(alice)
                else:
                    with boa.reverts():  # dev: active action
                        pk.commit_new_receiver(alice)
