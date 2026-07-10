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


def clamp_ema(rate: int) -> int:
    """Replicates the [MIN_TARGET_RATE, MAX_TARGET_RATE] clamp applied to the EMA read."""
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
        low = draw(st.integers(min_value=max(ref.MIN_LOW_RATIO, WAD - window), max_value=WAD - 1))
        return u0, low, high, shift

    low = draw(low_ratio_st)
    subtrahend = (WAD - u0) * (WAD - low)
    beta_lo = WAD + (subtrahend + WAD + u0 - 1) // u0  # smallest beta with inner >= WAD
    beta_hi = WAD + (WAD + 1) * subtrahend // u0        # largest beta with u_inf > WAD
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


def _debt_and_avail_for_utilization(reserves, u_inf, frac):
    """Pick a debt level whose resulting utilization is `frac`-of-the-way toward
    (just under) u_inf, so the state is always on the valid, non-underflowing
    branch of the curve. Returns (debt, avail, utilization)."""
    max_u = min(WAD, u_inf - 1)
    target_u = max_u * frac // WAD
    debt = reserves * target_u // WAD
    avail = reserves - debt
    return debt, avail, ref.utilization(avail, debt, 0)


@given(
    params=valid_params(),
    seed_rate=rate_st,
    reserves=reserves_st,
    frac=st.integers(min_value=0, max_value=WAD),
)
@settings(max_examples=1000, deadline=None)
def test_matches_reference(params, seed_rate, reserves, frac):
    """On-chain `parameters` and `rate()` equal the reference for any valid curve
    and controller state."""
    u0, low, high, shift = params
    ref_params = ref.get_params(u0, low, high)
    u_inf, A, r_minf = ref_params

    debt, avail, u = _debt_and_avail_for_utilization(reserves, u_inf, frac)
    r0 = clamp_ema(seed_rate)
    expected = ref.calculate_rate(ref_params, u, r0, shift)
    assume(expected >= 0)  # a negative rate would revert on-chain

    mp, ctrl, _ = _deploy(u0, low, high, shift, seed_rate)

    # parameters depend only on the curve args
    p = mp.parameters()
    assert (
        p.u_inf, p.A, p.r_minf,
        p.target_utilization, p.low_ratio, p.high_ratio, p.rate_shift,
    ) == (u_inf, A, r_minf, u0, low, high, shift)

    # rate() depends on the seeded EMA and the controller state
    ctrl.set_state(debt, avail, 0)
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
)
@settings(max_examples=500, deadline=None)
def test_rate_monotonic_in_utilization(params, reserves, f1, f2):
    """The borrow rate is non-decreasing in utilization."""
    u0, low, high, shift = params
    ref_params = ref.get_params(u0, low, high)
    u_inf = ref_params[0]

    lo_frac, hi_frac = sorted((f1, f2))
    debt_lo, avail_lo, u_lo = _debt_and_avail_for_utilization(reserves, u_inf, lo_frac)
    debt_hi, avail_hi, u_hi = _debt_and_avail_for_utilization(reserves, u_inf, hi_frac)

    # Keep the lower endpoint on the non-negative branch of the curve.
    r0 = clamp_ema(ref.DEFAULT_RATE)
    assume(u_hi > u_lo)
    assume(ref.calculate_rate(ref_params, u_lo, r0, shift) >= 0)
    assume(ref.calculate_rate(ref_params, u_hi, r0, shift) >= 0)

    mp, ctrl, _ = _deploy(u0, low, high, shift, ref.DEFAULT_RATE)

    ctrl.set_state(debt_lo, avail_lo, 0)
    rate_lo = mp.rate()
    ctrl.set_state(debt_hi, avail_hi, 0)
    rate_hi = mp.rate()

    assert rate_hi >= rate_lo
