"""
Hypothesis port of `test_lm_callback.py` - same scenarios, with `random()`,
`randrange()` and `choice()` replaced by drawn values.

Amounts are drawn as 1e18-scaled fractions and mapped onto state-dependent
bounds inside the loop, since hypothesis has to pick every value up front.
"""

import boa
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.utils.constants import MAX_UINT256

YEAR = 365 * 86400
WEEK = 7 * 86400
RATE_REDUCTION_TIME = YEAR  # ERC20CRV.vy:64

N_ITERATIONS = 20
N_BANDS = 10
ONE = 10**18

FRACTION = st.integers(min_value=0, max_value=ONE)

# The AMM needs > 100 wei of collateral per band, so unlike `randrange(1, ...)`
# deposits are floored away from dust - hypothesis probes the ends of every
# range, plain randomness never did.
MIN_DEPOSIT = 10**16
DEBT_FRACTION = st.integers(min_value=10**16, max_value=ONE)  # of max_borrowable


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


USER_STEP = st.fixed_dictionaries(
    {
        "withdraw": chance(50),
        "amount": FRACTION,  # withdrawn share of the collateral in the AMM
        "repay": FRACTION,  # repaid share of the debt (10% - 99% as before)
        "deposit": FRACTION,  # deposited share of the wallet balance
        "debt": DEBT_FRACTION,
    }
)

EXCHANGE_STEP = st.fixed_dictionaries(
    {
        "act_borrower1": chance(20),
        "dt_action": st.integers(min_value=1, max_value=YEAR // 5 - 1),
        "dt_claim": st.integers(min_value=1, max_value=YEAR // 20 - 1),
        "checkpoint_borrower1": chance(50),
        "checkpoint_borrower2": chance(50),
        "band": FRACTION,  # which of the tradeable bands the price is pushed into
        "price": FRACTION,  # where inside that band the oracle lands
        "borrower1": USER_STEP,
        "borrower2": USER_STEP,
    }
)


def accrue(crv, t0, t1, rate, future_epoch):
    """CRV per unit of collateral over [t0, t1], counted the way LMCallback counts it.

    Mirrors `_checkpoint_collateral_shares` (LMCallback.vy:125-163): the interval is
    split at the epoch end that was cached at `t0`, and everything past it accrues at
    CRV's rate *now*. The schedule is read from CRV (`rate` / `start_epoch_time`
    views), never from the callback's own bookkeeping, so a bug in that bookkeeping
    still shows up here.

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


def act(controller, amm, lm_callback, collateral_token, user, step):
    """Deposit or repay/withdraw for `user`; True if the model should checkpoint.

    Ends with an explicit `user_checkpoint` whenever it returns True. Not every
    action reaches the callback - a repay while soft-liquidated only lowers the debt
    and never moves bands (controller.vy:1037-1040), health can be too low to
    withdraw, and amounts can round down to nothing - and a model checkpoint without
    a matching contract one leaves the two caching different CRV epochs (`accrue`).
    """
    collateral_in_amm, borrowed_in_amm, debt, __ = controller.user_state(user)
    is_underwater = borrowed_in_amm > 0

    with boa.env.prank(user):
        if step["withdraw"] and collateral_in_amm > 0:
            amount = scale(step["amount"], 1, collateral_in_amm)
            if amount == collateral_in_amm:
                controller.repay(debt)
            elif controller.health(user) > 0:
                repay_amount = debt // 10 + (debt * 9 // 10) * step["repay"] * 99 // (
                    100 * ONE
                )
                if repay_amount > 0:
                    controller.repay(repay_amount)
                if not is_underwater:
                    min_collateral_required = controller.min_collateral(
                        debt - repay_amount, N_BANDS
                    )
                    remove_amount = max(
                        min(collateral_in_amm - min_collateral_required, amount), 0
                    )
                    if remove_amount > 0:
                        controller.remove_collateral(remove_amount)
            lm_callback.user_checkpoint(user)
            assert amm.get_sum_xy(user)[1] == pytest.approx(
                lm_callback.user_collateral(user), rel=1e-13
            )
            return True

        if is_underwater:
            # A soft-liquidated position cannot take more collateral in
            return False

        deposit_amount = scale(
            step["deposit"], MIN_DEPOSIT, collateral_token.balanceOf(user) // 10
        )
        max_borrowable = controller.max_borrowable(deposit_amount, N_BANDS, user)
        borrow_amount = max_borrowable * step["debt"] // ONE
        acted = borrow_amount > 0
        if acted:
            if controller.loan_exists(user):
                controller.borrow_more(deposit_amount, borrow_amount)
            else:
                controller.create_loan(deposit_amount, borrow_amount, N_BANDS)
            lm_callback.user_checkpoint(user)
        assert amm.get_sum_xy(user)[1] == pytest.approx(
            lm_callback.user_collateral(user), rel=1e-13
        )
        return acted


def user_bands(amm, user):
    """The bands a user's position occupies; empty when there is no position."""
    n1, n2 = amm.read_user_tick_numbers(user)
    return [] if n1 == n2 else list(range(n1, n2 + 1))


def tradeable_bands(amm, users):
    """The bands around the oracle price that a single trade can reach."""
    p_o = amm.price_oracle()
    available = [band for user in users for band in user_bands(amm, user)]
    upper = sorted(band for band in available if amm.p_oracle_down(band) > p_o)[-5:]
    lower = sorted(band for band in available if amm.p_oracle_up(band) < p_o)[:5]
    return upper + lower


def trade_to_price(amm, price_oracle, admin, trader, p_target):
    """Move the oracle to `p_target` and let the trader arbitrage the AMM to it.

    Returns whether anything was actually traded: `AMM.exchange` bails out before
    touching the callback when either leg rounds down to 0 (AMM.vy:1029, 1059), and
    a model checkpoint without a matching contract one drifts the CRV epoch caches.
    """
    price_oracle.set_price(p_target, sender=admin)
    amount, pump = amm.get_amount_for_price(p_target)
    with boa.env.prank(trader):
        if pump:
            traded = amm.exchange(0, 1, amount, 0)
        else:
            traded = amm.exchange(1, 0, amount, 0)
    return traded[0] > 0


def test_simple_exchange(
    admin,
    trader,
    collateral_token,
    crv,
    controller,
    amm,
    lm_callback,
    minter,
):
    borrower1 = boa.env.generate_address("borrower1")
    borrower2 = boa.env.generate_address("borrower2")
    for b in (borrower1, borrower2):
        boa.deal(collateral_token, b, 1000 * 10**18)
        collateral_token.approve(controller, MAX_UINT256, sender=b)

    boa.env.time_travel(seconds=2 * WEEK + 5)

    controller.create_loan(10**21, 10**21 * 2600, 10, sender=borrower1)
    controller.create_loan(10**21, 10**21 * 1000, 10, sender=borrower2)

    # Time travel and checkpoint
    boa.env.time_travel(4 * WEEK)
    lm_callback.user_checkpoint(borrower1, sender=borrower1)
    lm_callback.user_checkpoint(borrower2, sender=borrower2)

    rewards_borrower1 = lm_callback.integrate_fraction(borrower1)
    rewards_borrower2 = lm_callback.integrate_fraction(borrower2)
    assert rewards_borrower1 == rewards_borrower2

    # Trader buys crvUSD --> collateral and takes a half of borrower1's deposit
    amm.exchange_dy(0, 1, 10**21 // 2, 2**255, sender=trader)

    # Time travel and checkpoint
    boa.env.time_travel(4 * WEEK)
    lm_callback.user_checkpoint(borrower1, sender=borrower1)
    lm_callback.user_checkpoint(borrower2, sender=borrower2)
    old_rewards_borrower1 = rewards_borrower1
    old_rewards_borrower2 = rewards_borrower2

    # borrower2 earned 2 times more CRV
    rewards_borrower1 = lm_callback.integrate_fraction(borrower1)
    rewards_borrower2 = lm_callback.integrate_fraction(borrower2)
    d_borrower1 = rewards_borrower1 - old_rewards_borrower1
    d_borrower2 = rewards_borrower2 - old_rewards_borrower2
    assert d_borrower2 / d_borrower1 == pytest.approx(2, rel=1e-15)

    minter.mint(lm_callback.address, sender=borrower1)
    assert crv.balanceOf(borrower1) == rewards_borrower1

    minter.mint(lm_callback.address, sender=borrower2)
    assert crv.balanceOf(borrower2) == rewards_borrower2


@given(
    steps=st.lists(EXCHANGE_STEP, min_size=N_ITERATIONS, max_size=N_ITERATIONS),
)
@settings(max_examples=25)
def test_gauge_integral_with_exchanges(
    admin,
    trader,
    collateral_token,
    borrowed_token,
    crv,
    lm_callback,
    controller,
    amm,
    price_oracle,
    minter,
    steps,
):
    with boa.env.anchor():
        borrower1 = boa.env.generate_address("borrower1")
        borrower2 = boa.env.generate_address("borrower2")
        for b in (borrower1, borrower2):
            boa.deal(collateral_token, b, 1000 * 10**18)
            collateral_token.approve(controller, MAX_UINT256, sender=b)
            borrowed_token.approve(controller, MAX_UINT256, sender=b)

        integral = 0  # ∫(balance * rate(t) / totalSupply(t) dt)

        # `truncated` is how much of `integral` the contract is allowed to have
        # floored away by the end of the run. Derivation, for one checkpoint
        # interval of length `dt` over which nothing moves:
        #
        #   n     - a band index; the user occupies N_BANDS of them
        #   y[n]  - collateral in band n            (AMM.bands_y)
        #   s[n]  - total shares in band n          (AMM.total_shares)
        #   u[n]  - the user's shares in band n     (AMM.read_user_ticks)
        #   S     - collateral in the whole AMM = sum(y[n]); the collateral token
        #           has 18 decimals here (LMCallback.vy:109 asserts it), so this is
        #           `collateral_token.balanceOf(amm)` with no precision factor
        #   RXT   - `rate_x_time`, CRV emitted AMM-wide over the interval
        #
        # The user's collateral is then `b = sum(u[n] * y[n] / s[n])`, which is what
        # `amm.get_sum_xy(user)[1]` returns, and the model credits `RXT * b / S`.
        #
        # 1. The contract gets there through four integer divisions:
        #
        #      cps[n]  = y[n] * 1e18 // s[n]                (AMM.vy:709, :1082)
        #      d_rpc   = rate * w * dt // S                 (LMCallback.vy:157-161)
        #      d_rps[n] = cps[n] * d_rpc // 1e18            (LMCallback.vy:190)
        #      d_rpu[n] = u[n] * d_rps[n] // 1e18           (LMCallback.vy:217)
        #
        #    and pays the user `sum(d_rpu[n])`.
        #
        # 2. Drop every `//` for a moment and compose them. `w` is the gauge
        #    relative weight, 1e18 for the single gauge in these fixtures, so
        #    `d_rpc = RXT * 1e18 / S` and band n contributes
        #
        #      u[n] * cps[n] * d_rpc / 1e36
        #        = u[n] * (y[n] * 1e18 / s[n]) * (RXT * 1e18 / S) / 1e36
        #        = u[n] * y[n] / s[n] * RXT / S
        #
        #    Summed over the bands that is `RXT * b / S` - the model term exactly.
        #    So the two only differ by what the four `//` throw away, and since a
        #    floor never rounds up, the contract can only land *below* the model.
        #
        # 3. The `cps[n]` floor is the one that can bite. Write the exact ratio as
        #    `C[n] = y[n] * 1e18 / s[n]`; the contract uses `cps[n] = floor(C[n])`,
        #    so it loses `e[n] = C[n] - cps[n]`, and `0 <= e[n] < 1`. Feeding that
        #    difference back through steps 3 and 4 above, band n pays at most
        #
        #      u[n] * e[n] * d_rpc / 1e36  <  u[n] * d_rpc / 1e36
        #                                   = u[n] * RXT / (1e18 * S)
        #
        #    less than the model. Summing over the user's bands leaves the whole
        #    interval's shortfall bounded by `sum(u[n]) * RXT / (1e18 * S)`, which
        #    is the accumulation in `update_integral` below - `checkpoint_shares` is
        #    `sum(u[n])`, read off the AMM at the same instant as balance and supply.
        #
        # 4. How big is that? Per band the bound relative to what the band should
        #    have paid is
        #
        #      [u[n] * RXT / (1e18 * S)] / [u[n] * y[n]/s[n] * RXT / S]
        #        = s[n] / (y[n] * 1e18)
        #
        #    Shares are minted at DEAD_SHARES (= 1000) per wei of collateral
        #    (AMM.vy:696) and then frozen - only `y[n]` moves afterwards. So for an
        #    untouched band `s[n] = 1000 * y[n]` and the bound is 1e-15 of the
        #    interval, i.e. the assertion stays as tight as the old `rel=1e-14` one.
        #    As soft liquidation drains `y[n]`, `s[n] / y[n]` grows, and the bound
        #    reaches 100% exactly when `y[n] * 1e18 < s[n]` - which is where
        #    `cps[n]` floors to 0 and the contract genuinely stops paying that band
        #    out (see dust.py, test_dust_collateral.py). The tolerance widens as far
        #    as the truncation provably reaches and no further.
        #
        # 5. The other three floors lose < 1 unit each per band per checkpoint,
        #    which propagates to well under a wei of CRV - swamped by `rounding` at
        #    the assertion, which covers the model's own `//` as well.
        #
        # Every input here (`read_user_ticks`, `get_sum_xy`, `balanceOf`) comes from
        # the AMM, so the bound never borrows a number from the callback it checks.
        truncated = 0

        checkpoint = boa.env.timestamp
        checkpoint_rate = crv.rate()
        checkpoint_future_epoch = crv.start_epoch_time() + RATE_REDUCTION_TIME
        checkpoint_supply = 0
        checkpoint_balance = 0
        checkpoint_shares = 0

        boa.env.time_travel(seconds=WEEK)

        def update_integral():
            nonlocal \
                checkpoint, \
                checkpoint_rate, \
                checkpoint_future_epoch, \
                integral, \
                truncated, \
                checkpoint_balance, \
                checkpoint_supply, \
                checkpoint_shares

            t1 = boa.env.timestamp
            rate_x_time, checkpoint_rate, checkpoint_future_epoch = accrue(
                crv, checkpoint, t1, checkpoint_rate, checkpoint_future_epoch
            )
            if checkpoint_supply > 0:
                integral += rate_x_time * checkpoint_balance // checkpoint_supply
                truncated += (
                    rate_x_time * checkpoint_shares // (10**18 * checkpoint_supply)
                )
            checkpoint = t1
            checkpoint_supply = collateral_token.balanceOf(amm)
            checkpoint_balance = amm.get_sum_xy(borrower1)[1]
            checkpoint_shares = sum(amm.read_user_ticks(borrower1))

        # borrower2 always deposits or withdraws; borrower1 does so more rarely
        for step in steps:
            boa.env.time_travel(seconds=step["dt_action"])

            if act(
                controller,
                amm,
                lm_callback,
                collateral_token,
                borrower2,
                step["borrower2"],
            ):
                update_integral()

            if step["act_borrower1"] and act(
                controller,
                amm,
                lm_callback,
                collateral_token,
                borrower1,
                step["borrower1"],
            ):
                update_integral()

            # Trader swaps
            bands = tradeable_bands(amm, (borrower1, borrower2))
            if len(bands) > 0:
                target_band = pick(step["band"], bands)
                p_target = scale(
                    step["price"],
                    amm.p_oracle_down(target_band),
                    amm.p_oracle_up(target_band),
                )
                if trade_to_price(amm, price_oracle, admin, trader, p_target):
                    update_integral()

            # Checking that updating the checkpoint in the same second does nothing
            # Also everyone can update: that should make no difference, too
            if step["checkpoint_borrower1"]:
                lm_callback.user_checkpoint(borrower1, sender=borrower1)
            if step["checkpoint_borrower2"]:
                lm_callback.user_checkpoint(borrower2, sender=borrower2)

            boa.env.time_travel(seconds=step["dt_claim"])

            total_collateral_from_amm = collateral_token.balanceOf(amm)
            total_collateral_from_lm_cb = lm_callback.total_collateral()
            if total_collateral_from_amm > 0 and total_collateral_from_lm_cb > 0:
                assert total_collateral_from_amm == pytest.approx(
                    total_collateral_from_lm_cb, rel=1e-13
                )

            with boa.env.prank(borrower1):
                crv_balance = crv.balanceOf(borrower1)
                with boa.env.anchor():
                    crv_reward = lm_callback.claimable_tokens(borrower1)
                minter.mint(lm_callback.address)
                assert crv.balanceOf(borrower1) - crv_balance == crv_reward

                update_integral()
                rewards = lm_callback.integrate_fraction(borrower1)
                # The contract floors at every step, so it can only land below the
                # model - and never further below than the truncation it is entitled
                # to (see `truncated`). `rounding` covers the model's own integer
                # division and the three lesser floors of step 5 there
                rounding = integral // 10**14 + 1
                assert integral - truncated - rounding <= rewards <= integral + rounding

            with boa.env.prank(borrower2):
                crv_balance = crv.balanceOf(borrower2)
                with boa.env.anchor():
                    crv_reward = lm_callback.claimable_tokens(borrower2)
                minter.mint(lm_callback.address)
                assert crv.balanceOf(borrower2) - crv_balance == crv_reward


@given(
    dt_deposit=st.integers(min_value=1, max_value=YEAR // 5 - 1),
    dt_trade=st.integers(min_value=1, max_value=YEAR // 5 - 1),
)
@settings(max_examples=10)
def test_full_repay_underwater(
    admin,
    trader,
    collateral_token,
    borrowed_token,
    crv,
    lm_callback,
    controller,
    amm,
    price_oracle,
    minter,
    dt_deposit,
    dt_trade,
):
    with boa.env.anchor():
        borrower1 = boa.env.generate_address("borrower1")
        borrower2 = boa.env.generate_address("borrower2")
        for b in (borrower1, borrower2):
            boa.deal(collateral_token, b, 1000 * 10**18)
            collateral_token.approve(controller, MAX_UINT256, sender=b)
            borrowed_token.approve(controller, MAX_UINT256, sender=b)

        boa.env.time_travel(seconds=dt_deposit)

        # borrower2 creates a high-LTV loan (will go underwater after trade)
        amount_borrower2 = 10**20
        controller.create_loan(
            amount_borrower2, amount_borrower2 * 2000, N_BANDS, sender=borrower2
        )

        # borrower1 creates a conservative loan (stays above water)
        amount_borrower1 = 10**20
        controller.create_loan(
            amount_borrower1, amount_borrower1 * 500, N_BANDS, sender=borrower1
        )

        boa.env.time_travel(seconds=dt_trade)

        # Trader pushes price so borrower2 goes underwater
        target_band = user_bands(amm, borrower2)[7]
        p_target = (amm.p_oracle_down(target_band) + amm.p_oracle_up(target_band)) // 2
        trade_to_price(amm, price_oracle, admin, trader, p_target)

        # borrower2 fully repays while underwater
        debt_borrower2 = controller.user_state(borrower2)[2]
        controller.repay(debt_borrower2, sender=borrower2)

        assert collateral_token.balanceOf(amm) == pytest.approx(
            lm_callback.total_collateral(), rel=1e-15
        )

        for user in (borrower1, borrower2):
            with boa.env.prank(user):
                crv_balance = crv.balanceOf(user)
                with boa.env.anchor():
                    crv_reward = lm_callback.claimable_tokens(borrower2)
                minter.mint(lm_callback.address)
                assert crv.balanceOf(user) - crv_balance == crv_reward
