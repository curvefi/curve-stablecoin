import boa
import pytest

from tests.utils.deployers import PEG_KEEPER_OFFBOARDING_DEPLOYER

pytestmark = pytest.mark.usefixtures(
    "add_initial_liquidity",
    "provide_token_to_peg_keepers",
    "mint_alice",
)


ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ADMIN_ACTIONS_DEADLINE = 3 * 86400


@pytest.fixture(scope="module")
def offboarding(receiver, admin, peg_keepers):
    hr = PEG_KEEPER_OFFBOARDING_DEPLOYER.deploy(receiver, admin, admin)
    with boa.env.prank(admin):
        for peg_keeper in peg_keepers:
            peg_keeper.set_new_regulator(hr)
    return hr


def test_offboarding(
    offboarding,
    stablecoin,
    peg_keepers,
    swaps,
    receiver,
    admin,
    alice,
    peg_keeper_updater,
):
    with boa.env.prank(admin):
        for peg_keeper in peg_keepers:
            stablecoin.eval(f"self.balanceOf[{peg_keeper.address}] += {10**18}")

    for peg_keeper, swap in zip(peg_keepers, swaps):
        assert offboarding.provide_allowed(peg_keeper) == 0
        assert offboarding.withdraw_allowed(peg_keeper) == 2**256 - 1

        # Able to withdraw
        with boa.env.prank(alice):
            swap.add_liquidity([0, 10**20], 0)
        balances = [swap.balances(0), swap.balances(1)]

        with boa.env.prank(peg_keeper_updater):
            assert peg_keeper.update()

        new_balances = [swap.balances(0), swap.balances(1)]
        assert new_balances[0] == balances[0]
        assert new_balances[1] < balances[1]


def test_set_killed(offboarding, peg_keepers, admin, stablecoin):
    peg_keeper = peg_keepers[0]
    stablecoin.eval(f"self.balanceOf[{peg_keeper.address}] += {10**18}")
    with boa.env.prank(admin):
        assert offboarding.is_killed() == 0

        assert offboarding.provide_allowed(peg_keeper) == 0
        assert offboarding.withdraw_allowed(peg_keeper) == 2**256 - 1

        offboarding.set_killed(1)
        assert offboarding.is_killed() == 1

        assert offboarding.provide_allowed(peg_keeper) == 0
        assert offboarding.withdraw_allowed(peg_keeper) == 2**256 - 1

        offboarding.set_killed(2)
        assert offboarding.is_killed() == 2

        assert offboarding.provide_allowed(peg_keeper) == 0
        assert offboarding.withdraw_allowed(peg_keeper) == 0

        offboarding.set_killed(3)
        assert offboarding.is_killed() == 3

        assert offboarding.provide_allowed(peg_keeper) == 0
        assert offboarding.withdraw_allowed(peg_keeper) == 0


def test_admin(reg, admin, alice, agg, receiver):
    # initial parameters
    assert reg.fee_receiver() == receiver
    assert reg.emergency_admin() == admin
    assert reg.is_killed() == 0
    assert reg.admin() == admin

    # third party has no access
    with boa.env.prank(alice):
        with boa.reverts():
            reg.set_fee_receiver(alice)
        with boa.reverts():
            reg.set_emergency_admin(alice)
        with boa.reverts():
            reg.set_killed(1)
        with boa.reverts():
            reg.set_admin(alice)

    # admin has access
    with boa.env.prank(admin):
        reg.set_fee_receiver(alice)
        assert reg.fee_receiver() == alice

        reg.set_emergency_admin(alice)
        assert reg.emergency_admin() == alice

        reg.set_killed(1)
        assert reg.is_killed() == 1
        with boa.env.prank(alice):  # emergency admin
            reg.set_killed(2)
            assert reg.is_killed() == 2

        reg.set_admin(alice)
        assert reg.admin() == alice
