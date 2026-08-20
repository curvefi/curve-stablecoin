"""Regression tests for LMCallback CRV emission bounds.

Every test here encodes an invariant the callback is supposed to hold. Emissions
can only be stopped by detaching the callback from its AMM, and a detached
callback latches `detached` and is permanently inert. Two things can go wrong
once the AMM stops calling it:

  Mechanism B - it keeps accruing off stale `collateral_per_share`. That map is
  only written by `callback_collateral_shares`, while `total_collateral` reads
  `balanceOf(AMM)` live, so the numerator freezes and the denominator does not.

  Mechanism A - a depositor arriving while detached never gets an `I_rpu`
  baseline seeded, and can then claim the band's entire banked `I_rps`.
  Reachable two ways: `test_detached_*` (path 1, the permissionless
  `user_checkpoint`) and `test_reattached_*` (path 2, `callback_user_shares`
  fired by the AMM after re-attachment - still open, needs the AMM to announce
  the detach).

The yardstick is `weight_budget`: the gauge's entitlement is bounded by
integral(rate * relative_weight dt), computed here from CRV's own schedule and
the GaugeController's weekly weights, never from the callback's bookkeeping.
"""

import boa
import pytest

from tests.utils.constants import MAX_UINT256, ZERO_ADDRESS

WEEK = 7 * 86400


def weight_budget(gauge_controller, cb, rate, t0, t1):
    """integral(rate * w dt) / 1e18, discretised per week like LMCallback.vy:135-161.

    Valid only inside a single CRV epoch, which every caller asserts.
    """
    total, t = 0, t0
    while t < t1:
        nxt = min((t // WEEK + 1) * WEEK, t1)
        w = gauge_controller.gauge_relative_weight(cb.address, t)
        total += rate * w * (nxt - t) // 10**18
        t = nxt
    return total


def fund(collateral_token, borrowed_token, controller, *users):
    for u in users:
        boa.deal(collateral_token, u, 10**23)
        boa.deal(borrowed_token, u, 10**24)
        collateral_token.approve(controller, MAX_UINT256, sender=u)
        borrowed_token.approve(controller, MAX_UINT256, sender=u)


def start_emissions(crv, lm_callback, admin):
    """Get past CRV's inflation delay so the schedule has one known constant rate.

    Also checkpoints the callback so its cached `inflation_rate` matches, and
    returns (rate, t0) for the budget computation.
    """
    boa.env.time_travel(seconds=2 * WEEK + 5)
    crv.update_mining_parameters()
    lm_callback.user_checkpoint(admin)
    rate = crv.rate()
    assert rate > 0
    return rate, lm_callback.I_rpc()[1]


def open_loan(controller, user, collateral=10**21):
    controller.create_loan(collateral, collateral * 1500, 10, sender=user)


def soft_liquidate(amm, price_oracle, admin, trader, borrowed_token, factor):
    """Move the oracle and let the trader arbitrage, pushing collateral out of bands."""
    p = amm.price_oracle() * factor // 100
    price_oracle.set_price(p, sender=admin)
    boa.deal(borrowed_token, trader, 10**26)
    borrowed_token.approve(amm, MAX_UINT256, sender=trader)
    amount, _pump = amm.get_amount_for_price(p)
    amm.exchange(0, 1, amount, 0, sender=trader)


# ── control ───────────────────────────────────────────────────────────────────


def test_weight_budget_attached(
    admin,
    trader,
    collateral_token,
    borrowed_token,
    crv,
    controller,
    amm,
    price_oracle,
    lm_callback,
    gauge_controller,
):
    """While attached, total mintable never exceeds the gauge's weight budget.

    This one passes today. It is the control: if it ever fails, the core
    accounting broke, not one of the three findings below.
    """
    with boa.env.anchor():
        users = [boa.env.generate_address(f"u{i}") for i in range(3)]
        fund(collateral_token, borrowed_token, controller, *users)
        rate, t0 = start_emissions(crv, lm_callback, admin)
        epoch0 = crv.start_epoch_time()

        for i, u in enumerate(users):
            open_loan(controller, u, (1 + i) * 10**20)
            boa.env.time_travel(seconds=5 * 86400)

        soft_liquidate(amm, price_oracle, admin, trader, borrowed_token, 70)
        boa.env.time_travel(seconds=2 * WEEK)
        controller.repay(controller.user_state(users[0])[2], sender=users[0])
        boa.env.time_travel(seconds=WEEK)

        for u in users:
            lm_callback.user_checkpoint(u)

        assert crv.start_epoch_time() == epoch0, "test crossed a CRV epoch"
        minted = sum(lm_callback.integrate_fraction(u) for u in users)
        budget = weight_budget(
            gauge_controller, lm_callback, rate, t0, boa.env.timestamp
        )
        assert minted <= budget, f"over-mint by {minted - budget}"


def test_unattached_callback_cannot_be_bricked(
    admin,
    collateral_token,
    borrowed_token,
    crv,
    controller,
    configurator,
    amm,
    deploy_lm_callback,
    gauge_controller,
):
    """A callback that has not gone live yet must not arm the detach latch.

    Deployment and attachment are separate transactions. If a checkpoint poked in
    between armed the latch, anyone could permanently brick every newly deployed
    callback before it ever started paying out.
    """
    with boa.env.anchor():
        borrower = boa.env.generate_address("borrower")
        fund(collateral_token, borrowed_token, controller, borrower)

        cb = deploy_lm_callback(amm)
        assert not cb.attached() and not cb.detached()

        # grief attempt: poke it while it is deployed but not yet attached
        cb.user_checkpoint(ZERO_ADDRESS)
        cb.user_checkpoint(borrower)
        assert not cb.detached(), "latch armed before the callback went live"

        # now wire it up for real; it must work normally
        boa.env.time_travel(seconds=2 * WEEK + 5)
        crv.update_mining_parameters()
        with boa.env.prank(admin):
            configurator.set_callback(controller, cb)
            gauge_controller.add_gauge(cb.address, 0, 10**18)

        open_loan(controller, borrower)
        boa.env.time_travel(seconds=2 * WEEK)
        cb.user_checkpoint(borrower)

        assert cb.attached() and not cb.detached()
        assert cb.integrate_fraction(borrower) > 0


# ── mechanism B: detached callback must not accrue ────────────────────────────


def test_detached_does_not_accrue_on_stale_cps(
    admin,
    trader,
    collateral_token,
    borrowed_token,
    crv,
    controller,
    configurator,
    amm,
    price_oracle,
    lm_callback,
):
    """Once detached, stale `collateral_per_share` must not keep earning.

    After a soft liquidation the AMM holds ~nothing, but the callback's frozen
    cps still says the bands are full, so `rate * w * dt / total_collateral`
    explodes.
    """
    with boa.env.anchor():
        honest = boa.env.generate_address("honest")
        fund(collateral_token, borrowed_token, controller, honest)
        start_emissions(crv, lm_callback, admin)

        open_loan(controller, honest)
        boa.env.time_travel(seconds=WEEK)
        lm_callback.user_checkpoint(honest)
        attached_week = lm_callback.integrate_fraction(honest)

        configurator.set_callback(controller, ZERO_ADDRESS, sender=admin)
        soft_liquidate(amm, price_oracle, admin, trader, borrowed_token, 50)

        boa.env.time_travel(seconds=WEEK)
        lm_callback.user_checkpoint(honest)
        detached_week = lm_callback.integrate_fraction(honest) - attached_week

        assert detached_week == 0, (
            f"detached callback accrued {detached_week} "
            f"({detached_week / attached_week:.3g}x an attached week)"
        )


# ── mechanism A: no baseline harvest ────────────────────────────────────────────


def test_detached_deposit_earns_nothing(
    admin,
    collateral_token,
    borrowed_token,
    crv,
    controller,
    configurator,
    lm_callback,
    minter,
):
    """Path 1: deposit while detached, then call the permissionless checkpoint.

    `I_rpu[user][n].rps` is never seeded because `callback_user_shares` is not
    fired, so the user claims the band's whole banked `I_rps` instantly.
    """
    with boa.env.anchor():
        honest = boa.env.generate_address("honest")
        latecomer = boa.env.generate_address("latecomer")
        fund(collateral_token, borrowed_token, controller, honest, latecomer)
        start_emissions(crv, lm_callback, admin)

        open_loan(controller, honest)
        boa.env.time_travel(seconds=4 * WEEK)
        lm_callback.user_checkpoint(honest)
        assert lm_callback.integrate_fraction(honest) > 0

        configurator.set_callback(controller, ZERO_ADDRESS, sender=admin)

        open_loan(controller, latecomer)
        lm_callback.user_checkpoint(latecomer)

        assert lm_callback.integrate_fraction(latecomer) == 0, (
            f"harvested {lm_callback.integrate_fraction(latecomer)} "
            f"for zero seconds of exposure"
        )


def test_detached_stays_within_weight_budget(
    admin,
    collateral_token,
    borrowed_token,
    crv,
    controller,
    configurator,
    lm_callback,
    gauge_controller,
):
    """The weight bound must survive detachment, whatever else changes."""
    with boa.env.anchor():
        honest = boa.env.generate_address("honest")
        latecomer = boa.env.generate_address("latecomer")
        fund(collateral_token, borrowed_token, controller, honest, latecomer)
        rate, t0 = start_emissions(crv, lm_callback, admin)
        epoch0 = crv.start_epoch_time()

        open_loan(controller, honest)
        boa.env.time_travel(seconds=4 * WEEK)
        lm_callback.user_checkpoint(honest)

        configurator.set_callback(controller, ZERO_ADDRESS, sender=admin)
        open_loan(controller, latecomer)
        lm_callback.user_checkpoint(latecomer)

        assert crv.start_epoch_time() == epoch0, "test crossed a CRV epoch"
        minted = sum(lm_callback.integrate_fraction(u) for u in (honest, latecomer))
        budget = weight_budget(
            gauge_controller, lm_callback, rate, t0, boa.env.timestamp
        )
        assert minted <= budget, (
            f"over-mint by {minted - budget} ({minted / budget:.2f}x budget)"
        )


def test_detached_stale_baseline_earns_nothing(
    admin,
    collateral_token,
    borrowed_token,
    crv,
    controller,
    configurator,
    amm,
    lm_callback,
    minter,
):
    """A baseline left behind by a closed position must not license a new one.

    `I_rpu` is not cleared on withdrawal, so a user who once held a position in a
    band range keeps a stale, non-zero `I_rpu[user][n].rps` there. While attached
    that is harmless - `deposit_range` re-seeds it on the way back in. While
    detached the re-seed never happens, so any guard that treats "non-zero
    baseline" as "legitimate holder" lets the stale value through, and the user
    harvests `new_shares * (I_rps_now - stale_baseline)`.
    """
    with boa.env.anchor():
        honest = boa.env.generate_address("honest")
        attacker = boa.env.generate_address("attacker")
        fund(collateral_token, borrowed_token, controller, honest, attacker)
        start_emissions(crv, lm_callback, admin)

        open_loan(controller, honest)

        # tiny position, checkpointed to seed a baseline, then fully exited
        open_loan(controller, attacker, 10**19)
        boa.env.time_travel(seconds=WEEK)
        lm_callback.user_checkpoint(attacker)
        earned = lm_callback.integrate_fraction(attacker)
        assert earned > 0
        controller.repay(controller.user_state(attacker)[2], sender=attacker)

        # I_rps grows for four weeks while the attacker holds nothing
        boa.env.time_travel(seconds=4 * WEEK)
        lm_callback.user_checkpoint(honest)

        configurator.set_callback(controller, ZERO_ADDRESS, sender=admin)

        # return with a 100x position into the same bands
        open_loan(controller, attacker)
        lm_callback.user_checkpoint(attacker)

        assert lm_callback.integrate_fraction(attacker) == earned, (
            f"stale baseline yielded "
            f"{lm_callback.integrate_fraction(attacker) - earned} extra"
        )


def test_reattached_deposit_earns_nothing_for_the_gap(
    admin,
    collateral_token,
    borrowed_token,
    crv,
    controller,
    configurator,
    lm_callback,
    minter,
):
    """Path 2: deposit lands during a detach window, then the callback is re-attached.

    Nothing calls the callback while it is detached, so a lazily-set guard never
    trips. On re-attachment the AMM legitimately fires `callback_user_shares`
    during the withdrawal, with real old shares against an unseeded baseline.
    """
    with boa.env.anchor():
        honest = boa.env.generate_address("honest")
        latecomer = boa.env.generate_address("latecomer")
        fund(collateral_token, borrowed_token, controller, honest, latecomer)
        start_emissions(crv, lm_callback, admin)

        open_loan(controller, honest)
        boa.env.time_travel(seconds=4 * WEEK)
        lm_callback.user_checkpoint(honest)

        configurator.set_callback(controller, ZERO_ADDRESS, sender=admin)
        lm_callback.user_checkpoint(ZERO_ADDRESS)
        open_loan(controller, latecomer)  # callback is never touched here
        configurator.set_callback(controller, lm_callback, sender=admin)

        # withdrawal fires callback_collateral_shares then callback_user_shares
        controller.repay(controller.user_state(latecomer)[2], sender=latecomer)

        assert lm_callback.integrate_fraction(latecomer) == 0, (
            f"harvested {lm_callback.integrate_fraction(latecomer)} across the gap"
        )
