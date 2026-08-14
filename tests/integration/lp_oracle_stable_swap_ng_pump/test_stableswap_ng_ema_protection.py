"""
StableSwap-NG virtual-price pump is neutralised by the EMA oracle
=================================================================

An un-hardened StableSwap-NG LP oracle reports

    price = portfolio_value(A, POOL.price_oracle(0)) * POOL.get_virtual_price() / 1e18

so the LP price scales linearly with the pool's virtual price.  An attacker that
can momentarily inflate the virtual price - by wash trading, or through a
misbehaving rate oracle of a pool coin - inflates the collateral price by the
same factor and can force a liquidation.  (See tests/integration/ERC4626_pump for
that attack carried out end to end against a naive oracle; there the manipulated
input is an ERC4626 share price, but the market-level mechanics are identical.)

``StableSwapNGLPOracle`` smooths the manipulable virtual price with an
exponential moving average:

    price = portfolio_value(A, POOL.price_oracle(0)) * EMA(virtual_price) / 1e18

The EMA module queues the freshly supplied virtual price for the *next* update
and only ever reports the previously-queued value blended over ``ema_time``.  As
a result an instantaneous (single-block) pump of the virtual price does not move
the reported price at all, so the victim's health does not budge and the forced
liquidation reverts with "Not enough rekt".

Steps of the attack the first test runs against the hardened market:
  1. The victim borrows the maximum against their collateral.
  2. The attacker trades through the whole victim position (pushes the AMM price
     up so all of the victim's collateral is converted to the borrowed token).
  3. The attacker pumps the pool virtual price by 20% (and even forces an oracle
     update) - the EMA absorbs none of it within the block.
  4. The attacker's liquidation attempt reverts; the victim stays solvent.

Note: the EMA only protects against *atomic* / single-block manipulation.
Sustaining the pump across multiple blocks for ~ema_time would still move the
price - that is the documented, accepted trade-off of EMA smoothing, covered by
the third test.

The second test covers the *downside* scenario.  The dampening is asymmetric:
upward virtual-price moves are smoothed, but downward moves are passed through
immediately, so a genuine loss of pool value is never hidden behind a stale,
too-high price.  A real pool virtual price falls when a coin's rate oracle
reprices down; such a drop lowers the oracle price in the same block and lets an
honestly under-collateralised borrower be liquidated.
"""

import boa

from tests.utils.constants import MAX_UINT256


N = 10
PUMP = 12 * 10**17  # +20% virtual price (1.2e18)
DUMP = 7 * 10**17  # -30% virtual price (0.7e18)


def test_stableswap_ng_ema_blocks_pump_liquidation(
    controller,
    amm,
    vault,
    pool,
    coin_idx,
    spot_lp_oracle,
    price_oracle,
    borrowed_token,
    collateral_token,
):
    victim = boa.env.generate_address("victim")
    attacker = boa.env.generate_address("attacker")

    # Virtual price is still 1.0, so the EMA is settled and the oracle reports
    # exactly the un-dampened LP price.
    p = price_oracle.price()
    assert p == spot_lp_oracle.lp_price(pool.address, coin_idx)

    # Approvals
    for user in (victim, attacker):
        with boa.env.prank(user):
            for token in (borrowed_token, collateral_token):
                for contract in (controller, amm, vault):
                    token.approve(contract.address, MAX_UINT256)

    # ----- 1) victim borrows the maximum -----
    victim_collateral = 100 * 10 ** collateral_token.decimals()
    boa.deal(collateral_token, victim, victim_collateral)
    with boa.env.prank(victim):
        max_debt = controller.max_borrowable(victim_collateral, N)
        controller.create_loan(victim_collateral, max_debt, N)
    assert controller.health(victim, True) > 0

    # ----- 2) attacker trades through the whole victim position -----
    attacker_reserves = 5 * victim_collateral * p // 10**18
    boa.deal(borrowed_token, attacker, attacker_reserves)
    with boa.env.prank(attacker):
        amm.exchange(0, 1, attacker_reserves, 0)

    victim_state = controller.user_state(victim)
    assert victim_state[0] == 0  # collateral fully converted
    assert victim_state[1] > 0  # now holds borrowed token

    health_before_pump = controller.health(victim, True)

    # ----- 3) attacker pumps the pool virtual price by 20% -----
    pool.set_virtual_price(PUMP)

    # Spot virtual price is pumped, but the EMA oracle does not reflect it: the
    # pumped value is only *queued*, the reported price stays put within the
    # block.
    assert pool.get_virtual_price() == PUMP
    assert price_oracle.price() == p

    # Even forcing an oracle state update (queuing the pumped value) changes
    # nothing in the same block - dt == 0, so the EMA returns its prev value.
    with boa.env.prank(attacker):
        price_oracle.price_w()
    assert price_oracle.price() == p

    # Victim health is unaffected by the pump and stays solvent.
    health_after_pump = controller.health(victim, True)
    assert health_after_pump > 0
    assert health_after_pump == health_before_pump

    # ----- 4) attacker's forced liquidation is impossible -----
    with boa.env.prank(attacker):
        with boa.reverts("Not enough rekt"):
            controller.liquidate(victim, 0)

    assert controller.loan_exists(victim)

    print("health (post-trade):", health_before_pump / 1e18)
    print("health (post-pump): ", health_after_pump / 1e18)
    print("EMA price held at:  ", price_oracle.price() / 1e18, "(== unmanipulated)")


def test_stableswap_ng_ema_passes_downside_through(
    controller,
    amm,
    vault,
    pool,
    coin_idx,
    spot_lp_oracle,
    price_oracle,
    borrowed_token,
    collateral_token,
):
    """A downward move of the pool virtual price must be reflected immediately
    (no EMA lag), so an honestly under-collateralised borrower can be liquidated.
    """
    victim = boa.env.generate_address("down_victim")
    liquidator = boa.env.generate_address("liquidator")

    # ----- clean baseline: virtual price back to 1.0 -----
    # (robust whether or not the pump test ran first on this shared market;
    #  min(spot, ema) picks the spot value, so a pumped EMA cannot leak in)
    pool.set_virtual_price(10**18)
    p = price_oracle.price()
    assert p == spot_lp_oracle.lp_price(pool.address, coin_idx)  # vp 1.0 -> spot price

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

    # ----- virtual price drops 30% (genuine loss of pool value) -----
    pool.set_virtual_price(DUMP)

    # The drop is passed through *immediately* - no price_w / time travel needed.
    # min(spot, ema) picks spot on the downside.
    assert pool.get_virtual_price() == DUMP
    assert price_oracle.price() == p * DUMP // 10**18  # full -30%, no lag

    # The borrower is now genuinely underwater.
    health_after = controller.health(victim, True)
    assert health_after < 0

    # ----- a liquidation is therefore possible (and correct) -----
    # No approval needed: health < 0 permits a bad-debt liquidation by anyone.
    boa.deal(borrowed_token, liquidator, max_debt)
    with boa.env.prank(liquidator):
        controller.liquidate(victim, 0)

    assert not controller.loan_exists(victim)

    print(
        "downside oracle:", p / 1e18, "->", price_oracle.price() / 1e18, "(full -30%)"
    )
    print("health:", health_before / 1e18, "->", health_after / 1e18)


def test_stableswap_ng_ema_sustained_pump_eventually_liquidates(
    controller,
    amm,
    vault,
    pool,
    coin_idx,
    spot_lp_oracle,
    price_oracle,
    borrowed_token,
    collateral_token,
    ema_time,
):
    """The EMA only *delays* an upward manipulation.  If the attacker sustains
    the pumped virtual price across several blocks (~ema_time), the EMA converges
    to the pumped value, the victim's health goes negative and the liquidation
    that was impossible atomically becomes possible.
    """
    victim = boa.env.generate_address("slow_victim")
    attacker = boa.env.generate_address("slow_attacker")

    # ----- clean baseline -----
    pool.set_virtual_price(10**18)
    p = price_oracle.price()
    assert p == spot_lp_oracle.lp_price(pool.address, coin_idx)

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

    # ----- attacker pumps the virtual price +20% and SUSTAINS it -----
    pool.set_virtual_price(PUMP)
    with boa.env.prank(attacker):
        price_oracle.price_w()  # queue the pumped value

    # Atomically the pump is still absorbed: victim stays solvent.
    assert price_oracle.price() == p
    assert controller.health(victim, True) > 0

    # Hold the pump and let blocks pass: the EMA climbs toward the pumped value.
    crossed = False
    print("\n  t/ema_time |  oracle  | health")
    for step in range(1, 11):
        boa.env.time_travel(seconds=ema_time // 100)
        with boa.env.prank(attacker):
            price_oracle.price_w()
        h = controller.health(victim, True)
        print(f"  {step:>9}  | {price_oracle.price() / 1e18:>7.4f}  | {h / 1e18:+.4f}")
        if h < 0 and not crossed:
            crossed = True

    assert crossed, "sustained pump should eventually push health < 0"
    assert controller.health(victim, True) < 0

    # ----- the liquidation that was impossible atomically now succeeds -----
    boa.deal(borrowed_token, attacker, max_debt)
    with boa.env.prank(attacker):
        controller.liquidate(victim, 0)
    assert not controller.loan_exists(victim)
