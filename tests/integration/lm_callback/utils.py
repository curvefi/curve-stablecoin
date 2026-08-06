"""Shared helpers for the `lm_callback` tests.

The hypothesis ports draw amounts as 1e18-scaled fractions and map them onto
state-dependent bounds inside the loop, since hypothesis has to pick every value
up front - `chance` / `scale` / `pick` do that mapping.
"""

from hypothesis import strategies as st

YEAR = 365 * 86400
WEEK = 7 * 86400
RATE_REDUCTION_TIME = YEAR  # ERC20CRV.vy:64

ONE = 10**18


def chance(percent):
    """True with `percent` probability - mirrors `random() < percent / 100`."""
    return st.integers(min_value=0, max_value=99).map(lambda x: x < percent)


def scale(fraction, lo, hi):
    """Map a 1e18-scaled fraction onto [lo, hi] - mirrors `randrange(lo, hi + 1)`."""
    if hi <= lo:
        return lo
    return lo + (hi - lo) * fraction // ONE


def pick(fraction, seq):
    """Map a 1e18-scaled fraction onto an element of `seq` - mirrors `choice(seq)`."""
    return seq[fraction * len(seq) // (ONE + 1)]


def accrue(crv, t0, t1, rate, future_epoch):
    """CRV per unit of collateral over [t0, t1], counted the way LMCallback counts it.

    Mirrors `_checkpoint_collateral_shares` (LMCallback.vy:125-163): the interval is
    split at the epoch end that was cached at `t0`, and everything past it accrues at
    CRV's rate *now*, so an epoch that started and ended in between is skipped - going
    more than a year without a checkpoint deliberately under-pays the gauge. The
    schedule is read from CRV (`rate` / `start_epoch_time` views), never from the
    callback's own bookkeeping, so a bug in that bookkeeping still shows up here.

    Callers must accrue right after every action that checkpoints the callback,
    otherwise the two caches drift apart and this stops mirroring anything.

    Returns the integral together with the refreshed (rate, future_epoch) cache.
    """
    new_rate, new_future_epoch = rate, future_epoch
    if t1 >= future_epoch:
        # exactly the condition on which the callback refreshes its cached rate
        new_rate = crv.rate()
        new_future_epoch = crv.start_epoch_time() + RATE_REDUCTION_TIME

    if t0 <= future_epoch < t1:
        rate_x_time = rate * (future_epoch - t0) + new_rate * (t1 - future_epoch)
    else:
        rate_x_time = rate * (t1 - t0)

    return rate_x_time, new_rate, new_future_epoch
