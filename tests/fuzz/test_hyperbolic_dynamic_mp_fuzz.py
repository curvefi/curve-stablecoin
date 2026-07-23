"""Property-based (hypothesis) layer for HyperbolicDynamicMP.

These sit on top of the example-based unit tests in
tests/unitary/mpolicies/hyperbolic_dynamic_mp and share the same pure-Python
reference model (tests.utils.hyperbolic_mp_reference). Both collaborators are
mocked, so this stays unit-scoped — hypothesis just explores the input space.

Each example deploys fresh mocks + policy so there is no state bleed between
generated cases (the mocks are cheap to redeploy).
"""

import boa
from boa import BoaError
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from tests.utils import hyperbolic_mp_reference as ref
from tests.utils.constants import WAD
from tests.utils.deployers import (
    HYPERBOLIC_DYNAMIC_MP_DEPLOYER,
    MOCK_RATE_CALCULATOR_DEPLOYER,
    MOCK_CONTROLLER_MP_DEPLOYER,
)


# --- reference helpers (only needed to steer/predict the fuzz) -------------


def clamp_target_rate(rate: int) -> int:
    """Replicates the [MIN_TARGET_RATE, MAX_TARGET_RATE] clamp applied to the calculator's rate."""
    return min(max(rate, ref.MIN_TARGET_RATE), ref.MAX_TARGET_RATE)


def params_valid(u0: int, alpha: int, beta: int) -> bool:
    """
    * inner = num - sub < WAD -> "invalid curve"   (caps u_inf; else A/r_minf overflow).
    * u_inf must be > WAD                          (to avoid div by zero in _calculate_rate at u=WAD)
    """
    numerator = (beta - WAD) * u0
    inner = numerator - (WAD - u0) * (WAD - alpha)
    if inner < WAD:  # inner >= WAD caps u_inf <= numerator (else A/r_minf overflow)
        return False
    u_inf = numerator * WAD // inner
    return u_inf > WAD


# --- strategies -----------------------------------------------------------

# These params pass all the assertions in HyperbolicDynamicMP._set_parameters()
util_st = st.integers(min_value=ref.MIN_TARGET_UTIL, max_value=ref.MAX_TARGET_UTIL)
low_ratio_st = st.integers(min_value=ref.MIN_LOW_RATIO, max_value=WAD - 1)
high_ratio_st = st.integers(min_value=WAD + 1, max_value=ref.MAX_HIGH_RATIO)
rate_shift_st = st.integers(min_value=0, max_value=ref.MAX_RATE_SHIFT)
# Per-second rate returned by the calculator; spans below MIN and above MAX so
# the clamp is exercised, capped well under any overflow.
rate_st = st.integers(min_value=0, max_value=ref.MAX_TARGET_RATE * 1000)
# Reserves / debt for building controller states. R = reserves, D = debt <= R.
reserves_st = st.integers(min_value=1, max_value=10**30)
# Accrued admin fees as a fraction of reserves. Spans nearly the whole reserve
# size so that both regimes are covered: fees <= available_balance (netted out)
# and fees > available_balance (no free liquidity, utilization pins at 100%).
#
# Capped strictly below WAD to respect the Controller's accounting invariant
# admin_fees <= available_balance + total_debt: fees are a fraction of accrued
# interest (controller.vy `accrued_interest * admin_percentage // WAD`), so every
# wei of them is backed by either outstanding debt or a repaid balance. Letting
# them reach 100% of reserves would drive total_reserves to zero, a state no
# Controller can produce and which the policy has no obligation to price.
fee_frac_st = st.integers(min_value=0, max_value=WAD - 1)


@st.composite
def valid_params(draw):
    """Generate (u0, low, high, shift) guaranteed to form a valid curve.

    Picks u0 and alpha freely, then chooses beta at/above the threshold that
    makes `inner >= WAD` (so `_get_params` cannot revert), instead of drawing
    blindly and filtering — which would discard almost every example.
    """
    u0 = draw(util_st)
    alpha = draw(low_ratio_st)
    shift = draw(rate_shift_st)

    # With numerator = (beta - WAD)*u0 and subtrahend = (WAD - u0)*(WAD - alpha),
    # the curve is valid iff  subtrahend + WAD <= numerator <= (WAD + 1)*subtrahend:
    #   lower bound -> inner >= WAD (caps u_inf <= numerator, no A/r_minf overflow),
    #   upper bound -> u_inf > WAD.
    subtrahend = (WAD - u0) * (WAD - alpha)
    beta_lo = max(WAD + (subtrahend + WAD + u0 - 1) // u0, WAD + 1)
    beta_hi = min(WAD + (WAD + 1) * subtrahend // u0, ref.MAX_HIGH_RATIO)
    assume(beta_lo <= beta_hi)
    beta = draw(st.integers(min_value=beta_lo, max_value=beta_hi))

    assume(params_valid(u0, alpha, beta))  # safety net for integer-flooring edges
    return u0, alpha, beta, shift


@st.composite
def field_valid_params(draw):
    """Per-field-valid (u0, low, high, shift), steered evenly across the three
    deploy outcomes. Uniform draws almost never hit the (measure-tiny) revert
    corners, so we pick a regime and construct params to land in it.
    """
    u0 = draw(util_st)
    shift = draw(rate_shift_st)
    regime = draw(st.sampled_from(["valid", "invalid_curve", "u_inf_100"]))

    if regime == "u_inf_100":
        # u_inf collapses to WAD only for a tiny subtrahend, i.e. low hugs WAD:
        # numerator > (WAD+1)*subtrahend  <=>  (WAD - low) <= window.
        high = draw(high_ratio_st)
        window = ((high - WAD) * u0 - 1) // ((WAD + 1) * (WAD - u0))
        assume(window >= 1)
        low = draw(
            st.integers(
                min_value=max(ref.MIN_LOW_RATIO, WAD - window), max_value=WAD - 1
            )
        )
        return u0, low, high, shift

    low = draw(low_ratio_st)
    subtrahend = (WAD - u0) * (WAD - low)
    beta_lo = WAD + (subtrahend + WAD + u0 - 1) // u0  # smallest beta with inner >= WAD
    beta_hi = WAD + (WAD + 1) * subtrahend // u0  # largest beta with u_inf > WAD
    if regime == "invalid_curve":
        hi = min(beta_lo - 1, ref.MAX_HIGH_RATIO)
        assume(WAD + 1 <= hi)
        high = draw(st.integers(min_value=WAD + 1, max_value=hi))
    else:  # valid
        lo, hi = max(beta_lo, WAD + 1), min(beta_hi, ref.MAX_HIGH_RATIO)
        assume(lo <= hi)
        high = draw(st.integers(min_value=lo, max_value=hi))
    return u0, low, high, shift


def _deploy(u0, low, high, shift, seed_rate):
    calc = MOCK_RATE_CALCULATOR_DEPLOYER.deploy(seed_rate)
    ctrl = MOCK_CONTROLLER_MP_DEPLOYER.deploy(boa.env.generate_address("fuzz_factory"))
    mp = HYPERBOLIC_DYNAMIC_MP_DEPLOYER.deploy(
        ctrl.address, calc.address, u0, low, high, shift
    )
    return mp, ctrl, calc


# --- properties -----------------------------------------------------------


def _state_for_utilization(reserves, u_inf, frac, fee_frac=0):
    """Build a controller state whose utilization is `frac` of the way to 100%.

    Utilization is measured against *net* reserves (`available + debt - fees`), so
    the debt has to be derived from that same net figure. Deriving it from gross
    `reserves` instead leaves the result scaled by `reserves / (reserves - fees)`,
    drifting further above `frac` the more fees have accrued.

    The result still lands slightly *under* `target_u` and never exactly on it:
    deriving the debt floors once, recovering the utilization floors again, and
    the two do not cancel. Writing `net * target_u = q * WAD + r`, the result is
    exactly `target_u - ceil(r / net)`, so equality would need `WAD` to divide
    `net * target_u` — true only by coincidence. The gap is 1 wei once
    `net >= WAD`, but the whole value for a tiny market (at `net = 1` every
    `target_u < WAD` floors the debt to zero).
    Returns (debt, avail, fees, utilization)."""
    max_u = min(WAD, u_inf - 1)
    target_u = max_u * frac // WAD
    fees = reserves * fee_frac // WAD
    net = reserves - fees  # what utilization is measured against; >= 1
    debt = net * target_u // WAD
    avail = reserves - debt
    u = ref.utilization(avail, debt, fees)
    assert 0 <= target_u - u <= (WAD + net - 1) // net  # within one representable step

    return debt, avail, fees, u


@given(
    params=valid_params(),
    seed_rate=rate_st,
    reserves=reserves_st,
    frac=st.integers(min_value=0, max_value=WAD),
    fee_frac=fee_frac_st,
)
@settings(max_examples=1000, deadline=None)
def test_matches_reference(params, seed_rate, reserves, frac, fee_frac):
    """On-chain `parameters` and `rate()` equal the reference for any valid curve
    and controller state."""
    u0, low, high, shift = params
    ref_params = ref.get_params(u0, low, high)
    u_inf, A, r_minf = ref_params

    debt, avail, fees, u = _state_for_utilization(reserves, u_inf, frac, fee_frac)
    r0 = clamp_target_rate(seed_rate)
    expected = ref.calculate_rate(ref_params, u, r0, shift)
    assume(expected >= 0)  # a negative rate would revert on-chain

    mp, ctrl, _ = _deploy(u0, low, high, shift, seed_rate)

    # parameters depend only on the curve args
    p = mp.parameters()
    assert (
        p.u_inf,
        p.A,
        p.r_minf,
        p.target_utilization,
        p.low_ratio,
        p.high_ratio,
        p.rate_shift,
    ) == (u_inf, A, r_minf, u0, low, high, shift)

    # rate() depends on the (clamped) calculator rate and the controller state
    ctrl.set_state(debt, avail, fees)
    assert mp.target_rate() == r0
    assert mp.rate() == expected


@given(params=field_valid_params())
@settings(max_examples=1000, deadline=None)
def test_params_correct_or_curve_revert(params):
    """Fuzz per-field-valid inputs steered evenly across the three outcomes: the
    constructor must either store reference-matching parameters, or revert with
    exactly one of the two curve-math messages — never anything else."""
    u0, low, high, shift = params
    try:
        mp, _, _ = _deploy(u0, low, high, shift, ref.DEFAULT_RATE)
        assert params_valid(u0, low, high)
    except BoaError as e:
        assert "invalid curve" in str(e) or "u_inf <= 100%" in str(e)
        assert not params_valid(u0, low, high)
        return


@given(
    params=valid_params(),
    reserves=reserves_st,
    f1=st.integers(min_value=0, max_value=WAD),
    f2=st.integers(min_value=0, max_value=WAD),
    fee_frac=fee_frac_st,
)
@settings(max_examples=500, deadline=None)
def test_rate_monotonic_in_utilization(params, reserves, f1, f2, fee_frac):
    """The borrow rate is non-decreasing in utilization, at any fee level."""
    u0, low, high, shift = params
    ref_params = ref.get_params(u0, low, high)
    u_inf = ref_params[0]

    lo_frac, hi_frac = sorted((f1, f2))
    debt_lo, avail_lo, fees_lo, u_lo = _state_for_utilization(
        reserves, u_inf, lo_frac, fee_frac
    )
    debt_hi, avail_hi, fees_hi, u_hi = _state_for_utilization(
        reserves, u_inf, hi_frac, fee_frac
    )

    # Keep the lower endpoint on the non-negative branch of the curve.
    r0 = clamp_target_rate(ref.DEFAULT_RATE)
    assume(u_hi > u_lo)
    assume(ref.calculate_rate(ref_params, u_lo, r0, shift) >= 0)
    assume(ref.calculate_rate(ref_params, u_hi, r0, shift) >= 0)

    mp, ctrl, _ = _deploy(u0, low, high, shift, ref.DEFAULT_RATE)

    ctrl.set_state(debt_lo, avail_lo, fees_lo)
    rate_lo = mp.rate()
    ctrl.set_state(debt_hi, avail_hi, fees_hi)
    rate_hi = mp.rate()

    assert rate_hi >= rate_lo


@given(
    params=valid_params(),
    seed_rate=rate_st,
    reserves=reserves_st,
    frac=st.integers(min_value=0, max_value=WAD),
    g1=fee_frac_st,
    g2=fee_frac_st,
)
@settings(max_examples=500, deadline=None)
def test_rate_survives_any_admin_fees(params, seed_rate, reserves, frac, g1, g2):
    """Accrued admin fees can never revert the policy, and only push the rate up.

    Regression for the DoS where `total_reserves = available + debt - fees` made
    `rate()` revert with "Reserves too small" whenever fees exceeded the
    available balance — which is guaranteed at 100% utilization, where the
    available balance is 0 and any accrued fee bricks the market.
    """
    u0, low, high, shift = params
    ref_params = ref.get_params(u0, low, high)
    u_inf = ref_params[0]
    r0 = clamp_target_rate(seed_rate)

    lo_fee, hi_fee = sorted((g1, g2))
    debt, avail, fees_lo, u_lo = _state_for_utilization(reserves, u_inf, frac, lo_fee)
    # Only the fee level moves, so read the second utilization off the *same*
    # books rather than rebuilding the state (which would also move the debt).
    fees_hi = reserves * hi_fee // WAD
    u_hi = ref.utilization(avail, debt, fees_hi)

    # More fees can only raise utilization, never lower it, and never past 100%.
    assert u_lo <= u_hi <= WAD

    assume(ref.calculate_rate(ref_params, u_lo, r0, shift) >= 0)
    assume(ref.calculate_rate(ref_params, u_hi, r0, shift) >= 0)

    mp, ctrl, _ = _deploy(u0, low, high, shift, seed_rate)

    ctrl.set_state(debt, avail, fees_lo)
    rate_lo = mp.rate()
    ctrl.set_state(debt, avail, fees_hi)
    rate_hi = mp.rate()

    assert rate_lo == ref.calculate_rate(ref_params, u_lo, r0, shift)
    assert rate_hi == ref.calculate_rate(ref_params, u_hi, r0, shift)
    assert rate_hi >= rate_lo


# --- future_rate vs. actually applying the action -------------------------

# An action is expressed as the (d_reserves, d_debt) pair `future_rate` takes:
#
#   deposit(x)  -> (+x,  0)      borrow(x) -> ( 0, +x)
#   withdraw(x) -> (-x,  0)      repay(x)  -> ( 0, -x)
#
# Really performing it moves the controller's books to
#
#   debt'      = debt + d_debt
#   available' = available + d_reserves - d_debt   (borrowed coins leave the
#                                                   balance and become debt)
#   admin_fees' = admin_fees                       (untouched by all four)
#
# Substituting that into `_get_utilization` collapses both of the policy's
# guards into statements about the post-action books, which is what makes the
# applicable/unapplicable split below exact rather than approximate:
#
#   "Negative debt"      <=>  debt' < 0
#   "Reserves too small" <=>  available' < admin_fees
#                             (total_reserves - total_debt == available' - fees)

ACTIONS = [
    "deposit",
    "withdraw",
    "borrow",
    "repay",
    "mixed",
    "over_withdraw",
    "over_borrow",
    "over_repay",
]


def _ref_rate_or_none(params, u, r0, shift):
    """Reference rate, or None where the curve goes negative (reverts on-chain)."""
    try:
        return ref.calculate_rate(params, u, r0, shift)
    except AssertionError:
        return None


@st.composite
def state_and_action(draw):
    """A valid curve, a solvent controller state, and one (d_reserves, d_debt) action.

    Fees are drawn against the whole market, so they may exceed the available
    balance — the regime where there is no free liquidity left and utilization
    pins at 100% rather than reverting. The three `over_*` regimes are
    constructed explicitly because uniformly drawn deltas essentially never land
    just past a guard.
    """
    u0, low, high, shift = draw(valid_params())
    u_inf = ref.get_params(u0, low, high)[0]
    reserves = draw(reserves_st)
    frac = draw(st.integers(min_value=0, max_value=WAD))
    debt, avail, _, _ = _state_for_utilization(reserves, u_inf, frac)
    fees = reserves * draw(fee_frac_st) // WAD

    free = max(avail - fees, 0)  # most that may leave the market
    excess = st.integers(min_value=1, max_value=reserves + 1)

    kind = draw(st.sampled_from(ACTIONS))
    if kind == "deposit":
        d_reserves, d_debt = draw(st.integers(min_value=0, max_value=reserves)), 0
    elif kind == "withdraw":
        d_reserves, d_debt = -draw(st.integers(min_value=0, max_value=free)), 0
    elif kind == "borrow":
        d_reserves, d_debt = 0, draw(st.integers(min_value=0, max_value=free))
    elif kind == "repay":
        d_reserves, d_debt = 0, -draw(st.integers(min_value=0, max_value=debt))
    elif kind == "mixed":  # both legs at once, either sign, in or out of bounds
        d_reserves = draw(st.integers(min_value=-(avail + 1), max_value=reserves))
        d_debt = draw(st.integers(min_value=-(debt + 1), max_value=free + 1))
    elif kind == "over_withdraw":
        d_reserves, d_debt = -(free + draw(excess)), 0
    elif kind == "over_borrow":
        d_reserves, d_debt = 0, free + draw(excess)
    else:  # over_repay
        d_reserves, d_debt = 0, -(debt + draw(excess))

    return u0, low, high, shift, debt, avail, fees, d_reserves, d_debt


@given(scenario=state_and_action(), seed_rate=rate_st)
@settings(max_examples=1000, deadline=None)
def test_future_rate_matches_applied_action(scenario, seed_rate):
    """`future_rate(dR, dD)` is exactly the `rate()` reached by really doing it.

    `future_rate` exists to quote the rate a borrower or depositor will land on,
    so the simulation must not drift from reality. For every action we either
    (a) reproduce the quote by writing the post-action books to the controller
    and calling plain `rate()`, or (b) show the action was never applicable, and
    that the simulation refuses it with the guard the real books would have hit.
    """
    u0, low, high, shift, debt, avail, fees, d_reserves, d_debt = scenario
    ref_params = ref.get_params(u0, low, high)
    target_rate = clamp_target_rate(seed_rate)

    mp, ctrl, _ = _deploy(u0, low, high, shift, seed_rate)
    ctrl.set_state(debt, avail, fees)

    debt_after = debt + d_debt
    avail_after = avail + d_reserves - d_debt

    # Unapplicable actions: rejected in the contract's own order (debt first),
    # and never applied to the controller. Both guards are conditional on the
    # delta's sign — a market whose fees already exceed its balance is a *state*,
    # not an action, so it must pin at 100% instead of reverting, while an action
    # that draws on liquidity that isn't there still has to be refused.
    if debt_after < 0:  # implies d_debt < 0, so the contract's gate is open
        with boa.reverts("Negative debt"):
            mp.future_rate(d_reserves, d_debt)
        return
    if (d_reserves < 0 or d_debt > 0) and avail_after < fees:
        with boa.reverts("Reserves too small"):
            mp.future_rate(d_reserves, d_debt)
        return

    # Surviving actions never write a negative balance: either the guard ran and
    # gave avail_after >= fees >= 0, or it was skipped, which means d_reserves >= 0
    # and d_debt <= 0 and so avail_after >= avail.
    assert avail_after >= 0

    # Simulating the action and applying it must give the same utilization...
    u = ref.utilization(avail, debt, fees, d_reserves, d_debt)
    assert u == ref.utilization(avail_after, debt_after, fees)

    # ...and therefore the same rate. The `None` arm covers the curve's negative
    # branch: unreachable for an in-range target_rate and a non-negative shift,
    # but if it ever is reached both paths must revert together rather than one
    # of them quoting a rate the market cannot land on.
    expected = _ref_rate_or_none(ref_params, u, target_rate, shift)
    if expected is None:
        with boa.reverts("Negative rate"):
            mp.future_rate(d_reserves, d_debt)
        ctrl.set_state(debt_after, avail_after, fees)
        with boa.reverts("Negative rate"):
            mp.rate()
        return

    assert mp.future_rate(d_reserves, d_debt) == expected
    ctrl.set_state(debt_after, avail_after, fees)
    assert mp.rate() == expected
