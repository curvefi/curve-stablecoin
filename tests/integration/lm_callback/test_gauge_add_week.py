"""A gauge added mid-week earns nothing until the following week boundary.

`GaugeController.add_gauge` registers the weight at `(block.timestamp + WEEK) //
WEEK * WEEK`, so `gauge_relative_weight` returns 0 for the remainder of the week in
which the gauge was added, and `LMCallback` multiplies its emission by that weight
(LMCallback.vy:151-163). Any model of the callback as `rate * balance / supply`
over-credits exactly that remainder.

The random walks in `test_as_gauge*.py` only stumble into this window when the first
action happens to land in it *and* CRV has already started emitting (`ERC20CRV` has a
one-day `INFLATION_DELAY`, before which `rate()` is 0 and nothing accrues either
way) - a slice of a few hours in a multi-year run. This test builds that state
directly: it registers its own callback one day into a week, so the zero-weight
window is a known six days and inflation has long been running.
"""

import boa

from tests.utils.constants import MAX_UINT256

WEEK = 7 * 86400
DAY = 86400


def test_no_rewards_before_week_boundary(
    admin,
    collateral_token,
    borrowed_token,
    crv,
    controller,
    configurator,
    amm,
    gauge_controller,
    deploy_lm_callback,
):
    with boa.env.anchor():
        borrower = boa.env.generate_address("borrower")
        boa.deal(collateral_token, borrower, 10**21)
        collateral_token.approve(controller, MAX_UINT256, sender=borrower)
        borrowed_token.approve(controller, MAX_UINT256, sender=borrower)

        # Land exactly one day into a week, so the gauge below is added with a
        # six-day zero-weight window ahead of it instead of whatever remainder the
        # wall clock happens to give the fixtures. Weeks are counted the way
        # GaugeController counts them, and the target is the week after next, not
        # the next one: that keeps the jump at WEEK + DAY at the very least, well
        # clear of CRV's one-day INFLATION_DELAY (`time_travel` takes a duration,
        # hence the `- now`)
        now = boa.env.timestamp
        boa.env.time_travel(seconds=(now // WEEK + 2) * WEEK + DAY - now)

        cb = deploy_lm_callback(amm)
        with boa.env.prank(admin):
            configurator.set_callback(controller, cb)
            gauge_controller.add_gauge(cb.address, 0, 10**18)

        # The constructor's `future_epoch_time_write` started CRV's inflation, so
        # emissions are running and only the gauge weight can be zero from here on
        assert crv.rate() > 0

        boundary = (boa.env.timestamp // WEEK + 1) * WEEK
        assert boundary - boa.env.timestamp == 6 * DAY
        assert (
            gauge_controller.gauge_relative_weight(cb.address, boa.env.timestamp) == 0
        )
        assert gauge_controller.gauge_relative_weight(cb.address, boundary) > 0

        controller.create_loan(10**21, 10**21 * 2000, 10, sender=borrower)
        assert cb.user_collateral(borrower) == 10**21

        # Three days of emissions inside the window: the gauge gets none of them
        boa.env.time_travel(seconds=3 * DAY)
        cb.user_checkpoint(borrower, sender=borrower)
        assert cb.integrate_fraction(borrower) == 0

        # Two equal windows on the far side of the boundary must accrue the same
        # amount - if the pre-boundary time were paid for, the first would be larger
        window = 2 * DAY
        boa.env.time_travel(seconds=boundary + window - boa.env.timestamp)
        cb.user_checkpoint(borrower, sender=borrower)
        first = cb.integrate_fraction(borrower)
        assert first > 0

        boa.env.time_travel(seconds=window)
        cb.user_checkpoint(borrower, sender=borrower)
        second = cb.integrate_fraction(borrower) - first
        assert first == second
