"""LMCallback rewards across the end of a band's share chain.

When a band is fully converted and a new loan deposits into it, the AMM ends the
band's share chain: the old holders' x and y leave the band as a credit and the
shares start again from 0 (`AMM.deposit_range`). The old holders keep their raw
shares for that credit, but those shares hold no collateral of the band any more.
The callback must therefore pay them what they earned up to the chain's end, and
nothing on the new chain's collateral.

The yardstick is `weight_budget`: integral(rate * relative_weight dt) from CRV's
own schedule and the GaugeController's weekly weights.
"""

import boa
import pytest

from tests.integration.lm_callback.test_emission_bounds import (
    start_emissions,
    weight_budget,
)
from tests.utils.constants import MAX_UINT256, ZERO_ADDRESS

WEEK = 7 * 86400
N_BANDS = 10
COLLATERAL = 10**21
DEBT = COLLATERAL * 1500


def new_borrower(name, collateral_token, borrowed_token, controller):
    borrower = boa.env.generate_address(name)
    boa.deal(collateral_token, borrower, 10 * COLLATERAL)
    boa.deal(borrowed_token, borrower, 10 * DEBT)
    collateral_token.approve(controller, MAX_UINT256, sender=borrower)
    borrowed_token.approve(controller, MAX_UINT256, sender=borrower)
    return borrower


def attach_new_callback(
    admin, amm, controller, configurator, gauge_controller, deploy_lm_callback
):
    """Replace the market's callback by a new one with gauge weight from next week."""
    cb = deploy_lm_callback(amm)
    with boa.env.prank(admin):
        configurator.set_callback(controller, cb)
        gauge_controller.add_gauge(cb.address, 0, 10**18)
    boa.env.time_travel(seconds=WEEK)
    return cb


def detach(admin, controller, configurator, lm_callback):
    configurator.set_callback(controller, ZERO_ADDRESS, sender=admin)
    lm_callback.user_checkpoint(ZERO_ADDRESS)
    assert lm_callback.detached()


def convert_fully(amm, price_oracle, admin, trader, borrower):
    """Move the oracle below the borrower's bands and buy all of its collateral."""
    p0 = price_oracle.price()
    n2 = amm.read_user_tick_numbers(borrower)[1]
    price_oracle.set_price(amm.p_oracle_down(n2) * 99 // 100, sender=admin)
    boa.env.time_travel(seconds=3600)
    amm.exchange(0, 1, 10**30, 0, sender=trader)
    assert amm.get_sum_xy(borrower)[1] == 0
    price_oracle.set_price(p0, sender=admin)
    boa.env.time_travel(seconds=3600)


def settle(cb, controller, how, user, keeper):
    if how == "repay":
        controller.repay(controller.user_state(user)[2], sender=user)
    else:
        getattr(cb, how)(user, sender=keeper)
    return cb.integrate_fraction(user)


def test_ended_chain_earns_nothing(
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
    """The old loan earns nothing on the new loan's collateral."""
    with boa.env.anchor():
        old = new_borrower("old_borrower", collateral_token, borrowed_token, controller)
        new = new_borrower("new_borrower", collateral_token, borrowed_token, controller)
        start_emissions(crv, lm_callback, admin)
        epoch0 = crv.start_epoch_time()

        controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=old)
        boa.env.time_travel(seconds=WEEK)
        convert_fully(amm, price_oracle, admin, trader, old)
        controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=new)
        assert amm.read_user_tick_numbers(new) == amm.read_user_tick_numbers(old)

        lm_callback.user_checkpoint(old)
        lm_callback.user_checkpoint(new)
        before = [lm_callback.integrate_fraction(u) for u in (old, new)]
        t0 = lm_callback.I_rpc()[1]

        boa.env.time_travel(seconds=3600)
        lm_callback.user_checkpoint(old)
        lm_callback.user_checkpoint(new)
        t1 = lm_callback.I_rpc()[1]
        assert crv.start_epoch_time() == epoch0, "test crossed a CRV epoch"
        earned = [
            lm_callback.integrate_fraction(u) - b for u, b in zip((old, new), before)
        ]
        budget = weight_budget(gauge_controller, lm_callback, crv.rate(), t0, t1)

        assert budget > 0
        assert earned[0] == 0
        assert sum(earned) <= budget
        # The new loan holds all of the collateral, but DEAD_SHARES of each band
        assert earned[1] == pytest.approx(budget, rel=1e-6)


@pytest.mark.parametrize("late_checkpoint", ["user_checkpoint", "claimable_tokens"])
def test_ended_chain_keeps_earned_rewards(
    admin,
    trader,
    collateral_token,
    borrowed_token,
    crv,
    controller,
    amm,
    price_oracle,
    lm_callback,
    late_checkpoint,
):
    """A late checkpoint pays exactly what a holder had earned when its chain ended.

    Two chains end in the same bands. A keeper checkpoints the first two loans in one
    run just before the deposit which ends their chain, in the other only three weeks
    after the second chain ended.
    """
    users = [
        new_borrower(f"borrower_{i}", collateral_token, borrowed_token, controller)
        for i in range(3)
    ]
    keeper = boa.env.generate_address("keeper")
    start_emissions(crv, lm_callback, admin)

    def run(checkpoint_at_end):
        earned = []
        with boa.env.anchor():
            controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=users[0])
            for i in range(2):
                boa.env.time_travel(seconds=WEEK)
                convert_fully(amm, price_oracle, admin, trader, users[i])
                if checkpoint_at_end:
                    lm_callback.user_checkpoint(users[i], sender=keeper)
                    earned.append(lm_callback.integrate_fraction(users[i]))
                # Ends the chain of users[i] in every band
                controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=users[i + 1])
                assert amm.read_user_tick_numbers(
                    users[i + 1]
                ) == amm.read_user_tick_numbers(users[i])

            if not checkpoint_at_end:
                boa.env.time_travel(seconds=3 * WEEK)
                for u in users[:2]:
                    getattr(lm_callback, late_checkpoint)(u, sender=keeper)
                    earned.append(lm_callback.integrate_fraction(u))
        return earned

    at_end = run(True)
    late = run(False)
    assert at_end[0] > 0 and at_end[1] > 0
    assert late == at_end


@pytest.mark.parametrize("how", ["user_checkpoint", "claimable_tokens", "repay"])
def test_attached_later_pays_chains_by_their_end(
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
    gauge_controller,
    deploy_lm_callback,
    how,
):
    """A callback attached to a running market.

    `early` holds as many shares as `holder`, but its chain ended before the callback
    was attached: it earns nothing from the callback. `holder`'s chain was running when
    the callback was attached and ended just over two weeks later. The callback first
    sees the bands at the deposit of `joiner`, a week after the attach: `holder` earns
    the same as `joiner`. Both are paid the same whether they are checkpointed in the
    block of the chain's end or weeks later.
    """
    early, holder, closer, joiner = [
        new_borrower(name, collateral_token, borrowed_token, controller)
        for name in ("early", "holder", "closer", "joiner")
    ]
    keeper = boa.env.generate_address("keeper")
    start_emissions(crv, lm_callback, admin)
    detach(admin, controller, configurator, lm_callback)

    def run(checkpoint_at_end):
        with boa.env.anchor():
            controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=early)
            convert_fully(amm, price_oracle, admin, trader, early)
            # Ends the chain of `early` while no callback is attached
            controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=holder)
            assert amm.read_user_tick_numbers(early) == amm.read_user_tick_numbers(
                holder
            )

            cb = attach_new_callback(
                admin,
                amm,
                controller,
                configurator,
                gauge_controller,
                deploy_lm_callback,
            )
            assert cb.integrate_fraction(early) == 0
            controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=joiner)
            boa.env.time_travel(seconds=WEEK)
            convert_fully(amm, price_oracle, admin, trader, holder)
            if checkpoint_at_end:
                for u in (early, holder, joiner):
                    cb.user_checkpoint(u, sender=keeper)
            # Ends the chain of `holder` and `joiner` while the callback is attached
            controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=closer)
            assert amm.read_user_tick_numbers(closer) == amm.read_user_tick_numbers(
                holder
            )

            boa.env.time_travel(seconds=3 * WEEK)
            return [
                settle(cb, controller, how, u, keeper) for u in (early, holder, joiner)
            ]

    at_end = run(True)
    late = run(False)
    assert at_end[0] == 0
    assert at_end[1] > 0
    assert at_end[1] == at_end[2]
    assert late == at_end


def test_replaced_callback_pays_nothing_for_chains_ended_before(
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
    gauge_controller,
    deploy_lm_callback,
):
    """A chain ended under the first callback earns nothing from its replacement.

    The second callback pays the holders of the chain still running when it was
    attached, and the holders who joined it later, the same per share.
    """
    users = [
        new_borrower(f"borrower_{i}", collateral_token, borrowed_token, controller)
        for i in range(3)
    ]
    start_emissions(crv, lm_callback, admin)

    controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=users[0])
    boa.env.time_travel(seconds=WEEK)
    convert_fully(amm, price_oracle, admin, trader, users[0])
    # Ends the chain of users[0] under the first callback
    controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=users[1])

    cb = attach_new_callback(
        admin, amm, controller, configurator, gauge_controller, deploy_lm_callback
    )
    lm_callback.user_checkpoint(ZERO_ADDRESS)
    assert lm_callback.detached()
    controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=users[2])
    boa.env.time_travel(seconds=2 * WEEK)

    earned = []
    for u in users:
        cb.user_checkpoint(u)
        earned.append(cb.integrate_fraction(u))
    assert earned[0] == 0
    assert earned[1] > 0
    assert earned[1] == earned[2]


def test_chain_ended_at_first_touch_earns_nothing(
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
    gauge_controller,
    deploy_lm_callback,
):
    """The new callback first sees the bands at the deposit which ends their chain.

    The old loan was converted before the callback was attached, so it had no
    collateral while attached and earns nothing; the new loan earns the bands.
    """
    old = new_borrower("old_borrower", collateral_token, borrowed_token, controller)
    new = new_borrower("new_borrower", collateral_token, borrowed_token, controller)
    start_emissions(crv, lm_callback, admin)
    detach(admin, controller, configurator, lm_callback)

    controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=old)
    convert_fully(amm, price_oracle, admin, trader, old)
    cb = attach_new_callback(
        admin, amm, controller, configurator, gauge_controller, deploy_lm_callback
    )
    controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=new)
    assert amm.read_user_tick_numbers(new) == amm.read_user_tick_numbers(old)
    boa.env.time_travel(seconds=WEEK)

    cb.user_checkpoint(old)
    cb.user_checkpoint(new)
    assert cb.integrate_fraction(old) == 0
    assert cb.integrate_fraction(new) > 0


def test_same_callback_set_again_keeps_ended_chains(
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
    """Setting the same callback again changes nothing for a chain ended under it."""
    users = [
        new_borrower(f"borrower_{i}", collateral_token, borrowed_token, controller)
        for i in range(2)
    ]
    start_emissions(crv, lm_callback, admin)

    def run(set_again):
        with boa.env.anchor():
            controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=users[0])
            boa.env.time_travel(seconds=WEEK)
            convert_fully(amm, price_oracle, admin, trader, users[0])
            controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=users[1])
            with boa.env.anchor():
                lm_callback.user_checkpoint(users[0])
                at_end = lm_callback.integrate_fraction(users[0])
            if set_again:
                configurator.set_callback(controller, lm_callback, sender=admin)
            boa.env.time_travel(seconds=2 * WEEK)
            lm_callback.user_checkpoint(users[0])
            assert lm_callback.integrate_fraction(users[0]) == at_end
            return at_end

    earned = run(False)
    assert earned > 0
    assert run(True) == earned


@pytest.mark.parametrize("away", ["other_callback", "no_callback"])
def test_reattached_callback_stays_inert(
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
    gauge_controller,
    deploy_lm_callback,
    away,
):
    """A callback set again after another one (or none) pays nothing more.

    Nothing armed its latch while it was away, and a loan joined the running
    chain meanwhile with no baseline in it. Attaching it again latches it.
    """
    users = [
        new_borrower(f"borrower_{i}", collateral_token, borrowed_token, controller)
        for i in range(3)
    ]
    start_emissions(crv, lm_callback, admin)

    controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=users[0])
    boa.env.time_travel(seconds=WEEK)
    convert_fully(amm, price_oracle, admin, trader, users[0])
    # Ends the chain of users[0] under the callback
    controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=users[1])
    boa.env.time_travel(seconds=WEEK)
    for u in users:
        lm_callback.user_checkpoint(u)
    before = [lm_callback.integrate_fraction(u) for u in users]

    if away == "other_callback":
        attach_new_callback(
            admin, amm, controller, configurator, gauge_controller, deploy_lm_callback
        )
    else:
        configurator.set_callback(controller, ZERO_ADDRESS, sender=admin)
        boa.env.time_travel(seconds=WEEK)
    assert not lm_callback.detached()
    # Joins the chain of users[1] while the callback is away
    controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=users[2])
    configurator.set_callback(controller, lm_callback, sender=admin)
    boa.env.time_travel(seconds=2 * WEEK)

    for u in users:
        lm_callback.user_checkpoint(u)
    assert [lm_callback.integrate_fraction(u) for u in users] == before
    controller.repay(controller.debt(users[2]), sender=users[2])
    assert lm_callback.integrate_fraction(users[2]) == 0
    assert lm_callback.detached()


def test_first_band_ended_before_attach_keeps_other_bands(
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
    gauge_controller,
    deploy_lm_callback,
):
    """A loan whose first bands read 0 shares still earns in its other bands.

    11 / 20 of the old loan was converted, which emptied its first 5 bands, and a new
    loan ended the chains of those bands before the callback was attached. The old
    loan's shares there read 0, and it is paid for the collateral of its other bands.
    """
    old = new_borrower("old_borrower", collateral_token, borrowed_token, controller)
    closer = new_borrower("closer", collateral_token, borrowed_token, controller)
    joiner = new_borrower("joiner", collateral_token, borrowed_token, controller)
    start_emissions(crv, lm_callback, admin)
    epoch0 = crv.start_epoch_time()
    detach(admin, controller, configurator, lm_callback)

    controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=old)
    p0 = price_oracle.price()
    n2 = amm.read_user_tick_numbers(old)[1]
    price_oracle.set_price(amm.p_oracle_down(n2) * 99 // 100, sender=admin)
    boa.env.time_travel(seconds=3600)
    amm.exchange_dy(0, 1, COLLATERAL * 11 // 20, 10**30, sender=trader)
    price_oracle.set_price(p0, sender=admin)
    boa.env.time_travel(seconds=3600)
    # Ends the chain of `old` in its emptied bands while no callback is attached
    controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=closer)
    assert amm.read_user_tick_numbers(closer) == amm.read_user_tick_numbers(old)

    cb = attach_new_callback(
        admin, amm, controller, configurator, gauge_controller, deploy_lm_callback
    )
    controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=joiner)
    ticks = amm.read_user_ticks(old)
    assert ticks[0] == 0
    assert ticks[-1] > 0

    users = (old, closer, joiner)
    for u in users:
        cb.user_checkpoint(u)
    before = [cb.integrate_fraction(u) for u in users]
    t0 = cb.I_rpc()[1]

    boa.env.time_travel(seconds=3600)
    for u in users:
        cb.user_checkpoint(u)
    t1 = cb.I_rpc()[1]
    assert crv.start_epoch_time() == epoch0, "test crossed a CRV epoch"
    earned = [cb.integrate_fraction(u) - b for u, b in zip(users, before)]
    budget = weight_budget(gauge_controller, cb, crv.rate(), t0, t1)

    assert budget > 0
    assert sum(earned) <= budget
    # 9 / 20 of the old loan's collateral is left, of 49 / 20 in the AMM
    assert earned[0] == pytest.approx(budget * 9 // 49, rel=1e-6)
