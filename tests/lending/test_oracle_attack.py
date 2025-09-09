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
from tests.utils.constants import MAX_UINT256


@pytest.fixture(scope="module")
def market_type():
    # Ensure we test against the lending market setup from tests/conftest.py
    return "lending"


@pytest.fixture(scope="module")
def borrow_cap():
    # Use the dedicated fixture to set an effectively-unbounded cap for this test module
    return MAX_UINT256


@given(
    victim_gap=st.floats(min_value=15 / 866, max_value=0.9),
    victim_bins=st.integers(min_value=4, max_value=50)
)
@settings(max_examples=10000)
@pytest.mark.xfail(strict=True)
def test_vuln(vault, controller, amm, admin, borrowed_token, price_oracle, collateral_token, accounts,
                victim_gap, victim_bins):
    victim = accounts[1]
    hacker = accounts[2]

    # victim loan
    victim_collateral_lent = int(10_000e18)
    price_manipulation = 15 / 866  # 866-second price oracle manipulation during 15 second (1 block)
    manipulation_time = 13  # time between two blocks

    p = price_oracle.price()

    # Configure dynamic fee for this scenario
    with boa.env.prank(admin):
        controller.set_amm_fee(int(0.00001 * 1e18))

    # hacker
    hacker_crvusd_reserves = victim_collateral_lent * p // 10**18

    # approve everything
    for user in (hacker, victim):
        with boa.env.prank(user):
            for token in (borrowed_token, collateral_token):
                for contract in (controller, amm, vault):
                    token.approve(contract.address, MAX_UINT256)

    # add crvUSD to the vault
    with boa.env.prank(admin):
        b_amount = victim_collateral_lent * p // 10**18
        boa.deal(borrowed_token, admin, b_amount)
        borrowed_token.approve(vault.address, MAX_UINT256)
        vault.deposit(b_amount)

    # victim creates a loan
    with boa.env.prank(victim):
        victim_borrow = int((1 - victim_gap) * controller.max_borrowable(victim_collateral_lent, victim_bins))
        boa.deal(collateral_token, victim, victim_collateral_lent)
        controller.create_loan(victim_collateral_lent, victim_borrow, victim_bins)
        initial_health = controller.health(victim, True) / 1e18

    # hacker manipulates price oracle
    with boa.env.prank(hacker):
        boa.deal(borrowed_token, hacker, hacker_crvusd_reserves)
        amm.exchange(0, 1, hacker_crvusd_reserves, 0)

    # update oracle price
    with boa.env.prank(admin):
        new_p = int(p * (1 + price_manipulation))
        price_oracle.set_price(new_p)

    boa.env.time_travel(manipulation_time)

    with boa.env.prank(hacker):
        victim_health = controller.health(victim, True) / 1e18
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


@pytest.mark.xfail(strict=True)
def test_vuln_lite(vault, controller, amm, admin, borrowed_token, price_oracle, collateral_token, accounts):
    victim_gap = 0
    victim_bins = 4
    victim = accounts[1]
    hacker = accounts[2]

    # victim loan
    victim_collateral_lent = int(10_000_000e18)
    price_manipulation = 15 / 866  # 866-second price oracle manipulation during 15 second (1 block)
    manipulation_time = 13  # time between two blocks

    p = price_oracle.price()

    # Configure dynamic fee for this scenario
    with boa.env.prank(admin):
        controller.set_amm_fee(int(0.00001 * 1e18))

    # hacker
    hacker_crvusd_reserves = victim_collateral_lent * p // 10**18

    # approve everything
    for user in (hacker, victim):
        with boa.env.prank(user):
            for token in (borrowed_token, collateral_token):
                for contract in (controller, amm, vault):
                    token.approve(contract.address, MAX_UINT256)

    # add crvUSD to the vault
    with boa.env.prank(admin):
        b_amount = victim_collateral_lent * p // 10**18
        boa.deal(borrowed_token, admin, b_amount)
        borrowed_token.approve(vault.address, MAX_UINT256)
        vault.deposit(b_amount)

    # victim creates a loan
    with boa.env.prank(victim):
        victim_borrow = int((1 - victim_gap) * controller.max_borrowable(victim_collateral_lent, victim_bins))
        boa.deal(collateral_token, victim, victim_collateral_lent)
        controller.create_loan(victim_collateral_lent, victim_borrow, victim_bins)
        initial_health = controller.health(victim, True) / 1e18

    # hacker manipulates price oracle
    with boa.env.prank(hacker):
        boa.deal(borrowed_token, hacker, hacker_crvusd_reserves)
        amm.exchange(0, 1, hacker_crvusd_reserves, 0)

    # update oracle price
    with boa.env.prank(admin):
        new_p = int(p * (1 + price_manipulation))
        price_oracle.set_price(new_p)

    boa.env.time_travel(manipulation_time)

    with boa.env.prank(hacker):
        victim_health = controller.health(victim, True) / 1e18
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
