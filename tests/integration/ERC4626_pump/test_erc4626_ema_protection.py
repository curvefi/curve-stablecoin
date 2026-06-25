"""
ERC4626 share-price pump is neutralised by the EMA oracle
=========================================================

This is the counterpart of ``test_erc4626_pump_liquidation.py``.  The exact same
attack is run, but the market's oracle is swapped (via the Configurator) for
``OracleAndEMAERC4626``, which smooths the manipulable ERC4626 share price with
an exponential moving average:

    price = ORACLE.price() * EMA(VAULT.convertToAssets(1e18)) / 1e18

The EMA module queues the freshly supplied share price for the *next* update and
only ever reports the previously-queued value blended over ``ema_time``.  As a
result an instantaneous (single-block) pump of the share price does not move the
reported price at all, so the victim's health does not budge and the forced
liquidation reverts with "Not enough rekt".

Steps (identical to the successful attack, only the oracle differs):
  1. Swap the market oracle to OracleAndEMAERC4626 via the Configurator.
  2. The victim borrows the maximum against their collateral.
  3. The attacker trades through the whole victim position.
  4. The attacker pumps the VAULT share price by 20% (and even forces an oracle
     update) - the EMA absorbs none of it within the block.
  5. The attacker's liquidation attempt reverts; the victim stays solvent.

Note: the EMA only protects against *atomic* / single-block manipulation.
Sustaining the pump across multiple blocks for ~ema_time would still move the
price - that is the documented, accepted trade-off of EMA smoothing and is out
of scope here.

The second test covers the *downside* scenario.  The dampening is asymmetric:
upward share-price moves are smoothed, but downward moves are passed through
immediately, so a genuine loss of vault value is never hidden behind a stale,
too-high price.  A drop in the share price therefore lowers the oracle price in
the same block and lets an honestly under-collateralised borrower be liquidated.
"""

import boa

from tests.utils.constants import MAX_UINT256


N = 10
PUMP = 12 * 10**17  # +20% share price (1.2e18)
DUMP = 7 * 10**17  # -30% share price (0.7e18)


def test_erc4626_ema_blocks_pump_liquidation(
    controller,
    amm,
    vault,
    admin,
    configurator,
    base_oracle,
    dummy_vault,
    ema_oracle,
    borrowed_token,
    collateral_token,
):
    victim = boa.env.generate_address("victim")
    attacker = boa.env.generate_address("attacker")

    # ----- 1) swap the market oracle to the EMA-hardened one -----
    # Share price is still 1.0, so the EMA oracle reports the same price as the
    # current one (zero deviation).
    p = ema_oracle.price()
    assert p == base_oracle.price()
    with boa.env.prank(admin):
        configurator.set_price_oracle(controller, ema_oracle, MAX_UINT256)

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
    assert controller.health(victim, True) > 0

    # ----- 3) attacker trades through the whole victim position -----
    attacker_reserves = 5 * victim_collateral * p // 10**18
    boa.deal(borrowed_token, attacker, attacker_reserves)
    with boa.env.prank(attacker):
        amm.exchange(0, 1, attacker_reserves, 0)

    victim_state = controller.user_state(victim)
    assert victim_state[0] == 0  # collateral fully converted
    assert victim_state[1] > 0  # now holds borrowed token

    health_before_pump = controller.health(victim, True)

    # ----- 4) attacker pumps the VAULT share price by 20% -----
    dummy_vault.set_share_price(PUMP)

    # Spot share price is pumped, but the EMA oracle does not reflect it: the
    # pumped value is only *queued*, the reported price stays put within the
    # block.
    assert dummy_vault.convertToAssets(10**18) == PUMP
    assert ema_oracle.price() == p

    # Even forcing an oracle state update (queuing the pumped value) changes
    # nothing in the same block - dt == 0, so the EMA returns its prev value.
    with boa.env.prank(attacker):
        ema_oracle.price_w()
    assert ema_oracle.price() == p

    # Victim health is unaffected by the pump and stays solvent.
    health_after_pump = controller.health(victim, True)
    assert health_after_pump > 0
    assert health_after_pump == health_before_pump

    # ----- 5) attacker's forced liquidation is impossible -----
    with boa.env.prank(attacker):
        with boa.reverts("Not enough rekt"):
            controller.liquidate(victim, 0)

    assert controller.loan_exists(victim)

    print("health (post-trade):", health_before_pump / 1e18)
    print("health (post-pump): ", health_after_pump / 1e18)
    print("EMA price held at:  ", ema_oracle.price() / 1e18, "(== unmanipulated)")


def test_erc4626_ema_passes_downside_through(
    controller,
    amm,
    vault,
    admin,
    configurator,
    base_oracle,
    dummy_vault,
    ema_oracle,
    borrowed_token,
    collateral_token,
):
    """A downward move of the vault share price must be reflected immediately
    (no EMA lag), so an honestly under-collateralised borrower can be liquidated.
    """
    victim = boa.env.generate_address("down_victim")
    liquidator = boa.env.generate_address("liquidator")

    # ----- clean baseline: share price 1.0, EMA settled, EMA oracle installed -----
    # (robust whether or not the pump test ran first on this shared market)
    dummy_vault.set_share_price(10**18)
    with boa.env.prank(admin):
        configurator.set_price_oracle(controller, ema_oracle, MAX_UINT256)
    p = ema_oracle.price()
    assert p == base_oracle.price()  # share price 1.0 -> oracle == base price

    # Approvals
    for user in (victim, liquidator):
        with boa.env.prank(user):
            for token in (borrowed_token, collateral_token):
                for contract in (controller, amm, vault):
                    token.approve(contract.address, MAX_UINT256)

    # ----- victim borrows the maximum (healthy) -----
    victim_collateral = 100 * 10 ** collateral_token.decimals()
    boa.deal(collateral_token, victim, victim_collateral)
    with boa.env.prank(victim):
        max_debt = controller.max_borrowable(victim_collateral, N)
        controller.create_loan(victim_collateral, max_debt, N)
    health_before = controller.health(victim, True)
    assert health_before > 0

    # ----- share price drops 30% (genuine loss of vault value) -----
    dummy_vault.set_share_price(DUMP)

    # The drop is passed through *immediately* - no price_w / time travel needed.
    # min(spot, ema) picks spot on the downside.
    assert dummy_vault.convertToAssets(10**18) == DUMP
    assert ema_oracle.price() == p * DUMP // 10**18  # full -30%, no lag

    # The borrower is now genuinely underwater.
    health_after = controller.health(victim, True)
    assert health_after < 0

    # ----- a liquidation is therefore possible (and correct) -----
    # No approval needed: health < 0 permits a bad-debt liquidation by anyone.
    boa.deal(borrowed_token, liquidator, max_debt)
    with boa.env.prank(liquidator):
        controller.liquidate(victim, 0)

    assert not controller.loan_exists(victim)

    print("downside oracle:", p / 1e18, "->", ema_oracle.price() / 1e18, "(full -30%)")
    print("health:", health_before / 1e18, "->", health_after / 1e18)


def test_erc4626_ema_sustained_pump_eventually_liquidates(
    controller,
    amm,
    vault,
    admin,
    configurator,
    base_oracle,
    dummy_vault,
    ema_oracle,
    borrowed_token,
    collateral_token,
    ema_time,
):
    """The EMA only *delays* an upward manipulation.  If the attacker sustains
    the pumped share price across several blocks (~ema_time), the EMA converges
    to the pumped value, the victim's health goes negative and the liquidation
    that was impossible atomically becomes possible.
    """
    victim = boa.env.generate_address("slow_victim")
    attacker = boa.env.generate_address("slow_attacker")

    # ----- clean baseline + EMA oracle installed -----
    dummy_vault.set_share_price(10**18)
    with boa.env.prank(admin):
        configurator.set_price_oracle(controller, ema_oracle, MAX_UINT256)
    p = ema_oracle.price()
    assert p == base_oracle.price()

    for user in (victim, attacker):
        with boa.env.prank(user):
            for token in (borrowed_token, collateral_token):
                for contract in (controller, amm, vault):
                    token.approve(contract.address, MAX_UINT256)

    # ----- victim borrows the maximum -----
    victim_collateral = 100 * 10 ** collateral_token.decimals()
    boa.deal(collateral_token, victim, victim_collateral)
    with boa.env.prank(victim):
        max_debt = controller.max_borrowable(victim_collateral, N)
        controller.create_loan(victim_collateral, max_debt, N)
    assert controller.health(victim, True) > 0

    # ----- attacker trades through the position (strips the collateral) -----
    # A pure upward pump alone would only make the position healthier; the
    # collateral must first be converted away, exactly as in the naive attack.
    attacker_reserves = 5 * victim_collateral * p // 10**18
    boa.deal(borrowed_token, attacker, attacker_reserves)
    with boa.env.prank(attacker):
        amm.exchange(0, 1, attacker_reserves, 0)
    assert controller.user_state(victim)[0] == 0  # collateral gone

    # ----- attacker pumps the share price +20% and SUSTAINS it -----
    dummy_vault.set_share_price(PUMP)
    with boa.env.prank(attacker):
        ema_oracle.price_w()  # queue the pumped value

    # Atomically the pump is still absorbed: victim stays solvent.
    assert ema_oracle.price() == p
    assert controller.health(victim, True) > 0

    # Hold the pump and let blocks pass: the EMA climbs toward the pumped value.
    crossed = False
    print("\n  t/ema_time |  oracle  | health")
    for step in range(1, 11):
        boa.env.time_travel(seconds=ema_time // 100)
        with boa.env.prank(attacker):
            ema_oracle.price_w()
        h = controller.health(victim, True)
        print(f"  {step:>9}  | {ema_oracle.price()/1e18:>7.0f}  | {h/1e18:+.4f}")
        if h < 0 and not crossed:
            crossed = True

    assert crossed, "sustained pump should eventually push health < 0"
    assert controller.health(victim, True) < 0

    # ----- the liquidation that was impossible atomically now succeeds -----
    boa.deal(borrowed_token, attacker, max_debt)
    with boa.env.prank(attacker):
        controller.liquidate(victim, 0)
    assert not controller.loan_exists(victim)
