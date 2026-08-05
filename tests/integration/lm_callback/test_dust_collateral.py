"""Once the AMM holds only dust collateral, the callback stops distributing.

`AMM.vy:1082` recomputes a band's `collateral_per_share = y * 1e18 //
total_shares[n]` after every exchange. Shares stay constant while `y` collapses
during soft liquidation, so once `y` is dust the ratio floors to **0** and
`LMCallback._checkpoint_collateral_shares` (`LMCallback.vy:192`) credits nothing -
even though `total_collateral()` is still nonzero and one borrower owns all of it.

The contract is conservative here: nobody is over-credited, that window's emission
is simply not distributed. But a plain `rate * balance / supply` model of the
callback - the one `test_gauge_integral_with_exchanges` builds - credits **100%**
of the interval (`balance / supply == 1/1`). That is the far end of the `truncated`
allowance those tests subtract from their model, and this file pins the cliff it
has to cover.

Per band the two models differ by `O(total_shares_n / (y_n * 1e18))`, invisible
until `y_n` is dust, so a random walk only hits it if it happens to drain the AMM
almost - but not quite - completely. These tests drain it deliberately with a
single `exchange_dy`, which buys an exact amount out and so leaves an exact
leftover behind.
"""

import boa
import pytest

from tests.utils.constants import DEAD_SHARES, MAX_UINT256

WEEK = 7 * 86400
N_BANDS = 10


def dust_threshold(deposit: int, n_bands: int = N_BANDS) -> int:
    """Smallest band collateral that still earns, in wei.

    A first deposit into an empty band mints `ds = (0 + DEAD_SHARES) * y // (0 + 1)`
    shares (`AMM.vy:696`), i.e. exactly `DEAD_SHARES` per wei deposited, and shares
    never change afterwards - only `y` does. So the band's
    `collateral_per_share = y * 1e18 // total_shares` reaches 0 as soon as

        y * 1e18 < DEAD_SHARES * y_deposited

    Later deposits mint pro rata (`ds = (s + DEAD_SHARES) * y // (total_y + 1)`,
    and `deposit_range` only accepts bands with `bands_x == 0`), so the
    `DEAD_SHARES`-per-wei ratio holds for a band with any number of depositors -
    pass the sum of what they put in.

    The last band to be soft-liquidated is `n2`, which holds a plain
    `y_per_band = deposit // n_bands` (`n1` gets the division remainder on top).
    """
    y_per_band = deposit // n_bands
    return DEAD_SHARES * y_per_band // 10**18


def open_loan(controller, collateral_token, borrowed_token, deposit):
    borrower = boa.env.generate_address("borrower")
    boa.deal(collateral_token, borrower, deposit)
    with boa.env.prank(borrower):
        collateral_token.approve(controller, MAX_UINT256)
        borrowed_token.approve(controller, MAX_UINT256)
        # The gauge earns nothing until the week after it was added (see
        # test_gauge_add_week.py) - get clear of that window before depositing
        boa.env.time_travel(seconds=WEEK)
        controller.create_loan(deposit, deposit * 2000, N_BANDS)
    return borrower


def test_no_rewards_on_dust_collateral(
    admin,
    trader,
    collateral_token,
    borrowed_token,
    crv,
    controller,
    amm,
    lm_callback,
    minter,
):
    with boa.env.anchor():
        deposit = 10**21
        borrower = open_loan(controller, collateral_token, borrowed_token, deposit)

        # A week of normal accrual: the sole borrower gets everything, and here the
        # balance/supply model is right
        boa.env.time_travel(seconds=WEEK)
        lm_callback.user_checkpoint(borrower, sender=borrower)
        accrued = lm_callback.integrate_fraction(borrower)
        assert accrued > 0

        # Soft-liquidate the position down to 1 wei of collateral
        amm.exchange_dy(0, 1, deposit - 1, MAX_UINT256, sender=trader)

        # Supply is nonzero and the borrower still owns all of it, so the
        # balance/supply model would keep crediting him 100% of the emission
        assert lm_callback.total_collateral() == 1
        assert lm_callback.user_collateral(borrower) == 1

        # This is the state in which `truncated` in test_lm_callback.py widens to
        # cover a whole interval, and this is the cutoff it widens around
        assert lm_callback.total_collateral() < dust_threshold(deposit)

        rate = crv.rate()
        assert rate > 0

        boa.env.time_travel(seconds=WEEK)
        lm_callback.user_checkpoint(borrower, sender=borrower)

        # ... but the contract credits nothing: every band's collateral_per_share
        # truncated to 0, so there is nothing left to claim either
        assert lm_callback.integrate_fraction(borrower) == accrued
        assert lm_callback.claimable_tokens(borrower, sender=borrower) == accrued

        # An uncompensated model is a whole interval of emissions ahead here
        # (`rate * dt` exactly, modulo a CRV epoch boundary inside the window) -
        # which is the size `truncated` has to reach for the assertion at the end of
        # every iteration of test_gauge_integral_with_exchanges to hold
        naive_integral = accrued + rate * WEEK
        assert naive_integral > accrued
        assert lm_callback.integrate_fraction(borrower) != naive_integral


@pytest.mark.parametrize("deposit", [10**19, 10**20, 10**21])
def test_dust_threshold(
    admin,
    trader,
    collateral_token,
    borrowed_token,
    crv,
    controller,
    amm,
    lm_callback,
    minter,
    deposit,
):
    """The cutoff is exactly `deposit_per_band * DEAD_SHARES / 1e18`, and it is a cliff.

    One wei below it the band pays nothing at all; at it the band pays the *full*
    emission again (`collateral_per_share` goes 0 -> 1, and the borrower owns every
    share). There is no gradual taper to warn a model that it is drifting.
    """
    with boa.env.anchor():
        borrower = open_loan(controller, collateral_token, borrowed_token, deposit)
        threshold = dust_threshold(deposit)
        assert threshold == deposit // N_BANDS // 10**15  # 1e-15 of the band

        boa.env.time_travel(seconds=WEEK)
        lm_callback.user_checkpoint(borrower, sender=borrower)
        rate = crv.rate()

        rewards = {}
        for leftover in (threshold - 1, threshold):
            # A nested anchor so both leftovers start from the same AMM state
            with boa.env.anchor():
                amm.exchange_dy(
                    0, 1, deposit - leftover, MAX_UINT256, sender=trader
                )
                assert lm_callback.total_collateral() == leftover

                lm_callback.user_checkpoint(borrower, sender=borrower)
                before = lm_callback.integrate_fraction(borrower)
                boa.env.time_travel(seconds=WEEK)
                lm_callback.user_checkpoint(borrower, sender=borrower)
                rewards[leftover] = lm_callback.integrate_fraction(borrower) - before

        assert rewards[threshold - 1] == 0
        assert rewards[threshold] == pytest.approx(rate * WEEK, rel=1e-9)
