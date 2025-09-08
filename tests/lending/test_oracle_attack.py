# Hypothetical 2-block attack (extremely hard to do, but should not be ignored).
# Found by MixBytes as a flash loan attack for vault token collaterals (not yet released feature).
# However the scope was extended (by Michael) to any vaults using assumption of a control over two subsequent blocks,
# 100M'ish real funds to use for attack (no flash loan) and full trust to block validator - attacker exposes all those 100Ms to
# validator to grab (and thereby prevent the attack) if they attempt this attack at all.
#
# This type of attack has never happened in real world, however preemptively was addressed
# in crvUSD markets by increasing AMM fee, and in lending by making a special dynamic fee

import boa
import pytest

from hypothesis import given, settings
from hypothesis import strategies as st
from tests.utils.deployers import LENDING_FACTORY_DEPLOYER, OLD_AMM_DEPLOYER, AMM_DEPLOYER, LL_CONTROLLER_DEPLOYER, VAULT_DEPLOYER, ERC20_MOCK_DEPLOYER


MAX = 2**256 - 1


@pytest.fixture(scope='module')
def collateral_token(admin):
    decimals = 18
    with boa.env.prank(admin):
        return ERC20_MOCK_DEPLOYER.deploy(decimals)


@pytest.fixture(scope='module')
def borrowed_token(stablecoin):
    return stablecoin


@pytest.fixture(scope='module')
def victim(accounts):
    return accounts[1]


@pytest.fixture(scope='module')
def hacker(accounts):
    return accounts[2]


@pytest.fixture(scope="module")
def factory_new(amm_impl, controller_impl, vault_impl, price_oracle_impl, mpolicy_impl, admin):
    with boa.env.prank(admin):
        return LENDING_FACTORY_DEPLOYER.deploy(amm_impl, controller_impl, vault_impl, price_oracle_impl, mpolicy_impl, admin, admin)


@pytest.fixture(scope="module")
def amm_old_interface():
    return OLD_AMM_DEPLOYER


@pytest.fixture(scope="module")
def factory_old(controller_impl, vault_impl, price_oracle_impl, mpolicy_impl, amm_old_interface, admin):
    # TODO is this really the old factory? I don't think so
    with boa.env.prank(admin):
        amm_impl = amm_old_interface.deploy_as_blueprint()
        return LENDING_FACTORY_DEPLOYER.deploy(amm_impl, controller_impl, vault_impl, price_oracle_impl, mpolicy_impl, admin, admin)


@pytest.fixture(scope='module')
def vault_new(factory_new, borrowed_token, collateral_token, price_oracle, admin):
    with boa.env.prank(admin):
        price_oracle.set_price(int(1e18))

        vault = VAULT_DEPLOYER.at(
            factory_new.create(
                borrowed_token.address, collateral_token.address,
                100, int(0.002 * 1e18), int(0.09 * 1e18), int(0.06 * 1e18),
                price_oracle.address, "Test"
            )[0]
        )

        boa.env.time_travel(120)

        return vault


@pytest.fixture(scope='module')
def vault_old(factory_old, borrowed_token, collateral_token, price_oracle, admin):
    with boa.env.prank(admin):
        price_oracle.set_price(int(1e18))

        vault = VAULT_DEPLOYER.at(
            factory_old.create(
                borrowed_token.address, collateral_token.address,
                100, int(0.006 * 1e18), int(0.09 * 1e18), int(0.06 * 1e18),
                price_oracle.address, "Test"
            )[0]
        )

        boa.env.time_travel(120)

        return vault


@pytest.fixture(scope='module')
def controller_new(vault_new, admin):
    controller = LL_CONTROLLER_DEPLOYER.at(vault_new.controller())
    with boa.env.prank(admin):
        controller.set_borrow_cap(2 ** 256 - 1)

    return controller


@pytest.fixture(scope='module')
def amm_new(vault_new):
    return AMM_DEPLOYER.at(vault_new.amm())


@pytest.fixture(scope='module')
def controller_old(vault_old, admin):
    controller = LL_CONTROLLER_DEPLOYER.at(vault_old.controller())
    with boa.env.prank(admin):
        controller.set_borrow_cap(2 ** 256 - 1)

    return controller


@pytest.fixture(scope='module')
def amm_old(vault_old):
    return OLD_AMM_DEPLOYER.at(vault_old.amm())


def template_vuln_test(vault, controller, amm, admin, borrowed_token, price_oracle, collateral_token, victim, hacker,
                       victim_gap, victim_bins, fee):

    # victim loan
    victim_collateral_lent = int(10_000_000e18)
    price_manipulation = 15 / 866  # 866-second price oracle manipulation during 15 second (1 block)
    manipulation_time = 13  # time between two blocks

    p = price_oracle.price()

    with boa.env.prank(admin):
        controller.set_amm_fee(int(fee * 1e18))

    # hacker
    hacker_crvusd_reserves = int(500_000_000e18)

    # approve everything
    for user in hacker, victim:
        with boa.env.prank(user):
            for token in borrowed_token, collateral_token:
                for contract in controller, amm, vault:
                    token.approve(contract.address, MAX)

    # add crvUSD to the vault
    with boa.env.prank(admin):
        b_amount = int(1_000_000_000e18)
        boa.deal(borrowed_token, admin, b_amount)
        borrowed_token.approve(vault.address, MAX)
        vault.deposit(b_amount)

    # victim creates a loan
    with boa.env.prank(victim):
        victim_borrow = int((1 - victim_gap) * controller.max_borrowable(victim_collateral_lent, victim_bins))
        boa.deal(collateral_token, victim, victim_collateral_lent)
        controller.create_loan(victim_collateral_lent, victim_borrow, victim_bins)
        initial_health = controller.health(victim, True) / 1e18
        # print("Victim health", initial_health)

    # hacker manipulates price oracle and liquidates the victim
    with boa.env.prank(hacker):
        boa.deal(borrowed_token, hacker, hacker_crvusd_reserves)
        spent, received = amm.exchange(0, 1, hacker_crvusd_reserves, 0)
        # print(f"Bought {received/1e18:.3f} for {spent/1e18:.2f}")

    # update oracle price
    with boa.env.prank(admin):
        new_p = int(p * (1 + price_manipulation))
        price_oracle.set_price(new_p)
        # print(f"Manipulated collateral price {new_p/1e18:.4f}")

    boa.env.time_travel(manipulation_time)

    with boa.env.prank(hacker):
        victim_health = controller.health(victim, True) / 1e18
        # print("Victim health", victim_health)

        with boa.reverts():
            controller.liquidate(victim, 0)

            # If liquidation succeeded
            crvusd_profit = borrowed_token.balanceOf(hacker) - hacker_crvusd_reserves
            print("crvusd profit", crvusd_profit / 1e18)
            collateral_profit = collateral_token.balanceOf(hacker)
            print("Collateral profit", collateral_profit / 1e18)
            profit = crvusd_profit + collateral_profit * (p / 1e18)
            print("Total profit", profit / 1e18)
            print(f"Health: {initial_health} -> {victim_health}")


# Commenting out as it doesn't test much in its current state.
@given(
    victim_gap=st.floats(min_value=15 / 866, max_value=0.9),
    victim_bins=st.integers(min_value=4, max_value=50)
)
@settings(max_examples=10000)
def test_vuln_new(vault_new, controller_new, amm_new, admin, borrowed_token, price_oracle, collateral_token, victim, hacker,
                  victim_gap, victim_bins):

    template_vuln_test(vault_new, controller_new, amm_new, admin, borrowed_token, price_oracle, collateral_token, victim, hacker,
                       victim_gap, victim_bins, fee=0.00001)  # Any fee is safe - even very low


@given(
    victim_gap=st.floats(min_value=15 / 866, max_value=0.9),
    victim_bins=st.integers(min_value=4, max_value=50)
)
@settings(max_examples=10000)
def test_vuln_old(vault_old, controller_old, amm_old, admin, borrowed_token, price_oracle, collateral_token, victim, hacker,
                  victim_gap, victim_bins):

    template_vuln_test(vault_old, controller_old, amm_old, admin, borrowed_token, price_oracle, collateral_token, victim, hacker,
                       victim_gap, victim_bins, fee=0.019)  # 1.9% fee or higher is safe
