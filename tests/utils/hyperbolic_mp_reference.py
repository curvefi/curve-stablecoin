"""Pure-Python reference model of HyperbolicDynamicMP's integer math.

Mirrors the contract's fixed-point arithmetic exactly (including EVM's
truncate-toward-zero signed division) so tests can assert bit-exact equality
against the deployed contract. Also re-exports the contract's constants so test
modules can reference them at import/parametrize time.

Shared by the example-based unit tests
(tests/unitary/mpolicies/hyperbolic_dynamic_mp) and the property-based fuzz
layer (tests/fuzz/test_hyperbolic_dynamic_mp_fuzz.py).
"""

from tests.utils.constants import WAD
from tests.utils.deployers import HYPERBOLIC_DYNAMIC_MP_DEPLOYER as _MP

SECONDS_PER_YEAR = 365 * 86400

# Constants mirrored from the contract
MIN_TARGET_UTIL = _MP._constants.MIN_TARGET_UTIL
MAX_TARGET_UTIL = _MP._constants.MAX_TARGET_UTIL
MIN_LOW_RATIO = _MP._constants.MIN_LOW_RATIO
MAX_HIGH_RATIO = _MP._constants.MAX_HIGH_RATIO
MAX_RATE_SHIFT = _MP._constants.MAX_RATE_SHIFT
MIN_TARGET_RATE = _MP._constants.MIN_TARGET_RATE
MAX_TARGET_RATE = _MP._constants.MAX_TARGET_RATE

# Default constructor parameters used across the suite (all within bounds)
DEFAULT_TARGET_UTILIZATION = 85 * 10**16  # 0.85
DEFAULT_LOW_RATIO = 5 * 10**17  # 0.5x base at 0% utilization
DEFAULT_HIGH_RATIO = 2 * 10**18  # 2x base at 100% utilization
DEFAULT_RATE_SHIFT = 0
# ~5% APR expressed as a per-second rate (5x the ~1% MIN_TARGET_RATE anchor);
# comfortably within [MIN, MAX]_TARGET_RATE.
DEFAULT_RATE = 1_585_489_600


def tdiv(a: int, b: int) -> int:
    """Signed division truncating toward zero, matching EVM SDIV / Vyper `//`.

    Python's `//` floors toward -inf, which differs for negative operands.
    """
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


def get_params(u0: int, alpha: int, beta: int):
    """Replicates `_get_params`. Returns (u_inf, A, r_minf); shift is set by the caller."""
    numerator = (beta - WAD) * u0
    subtrahend = (WAD - u0) * (WAD - alpha)
    u_inf = numerator * WAD // (numerator - subtrahend)
    A = (WAD - alpha) * u_inf // WAD * (u_inf - u0) // u0
    r_minf = alpha - (A * WAD // u_inf)
    return u_inf, A, r_minf


def utilization(
    available_balance: int,
    total_debt: int,
    admin_fees: int,
    d_reserves: int = 0,
    d_debt: int = 0,
) -> int:
    """Replicates `_get_utilization`.

    Both guards are conditional on the sign of the delta, mirroring the contract:

    * `debt` can only go negative when `d_debt` does, since `total_debt` is a
      uint256 on-chain.
    * The reserve guard is skipped unless the action actually takes liquidity out
      (`d_reserves < 0`) or draws on it (`d_debt > 0`). Skipping it is what stops
      accrued `admin_fees` exceeding the available balance from bricking `rate()`:
      that state is not an action, it just means there is no free liquidity, so
      the ratio overshoots and the `min(..., WAD)` below pins it at 100%.
    """
    total_reserves = available_balance + total_debt - admin_fees + d_reserves
    debt = total_debt + d_debt
    if d_debt < 0:
        assert debt >= 0, "Negative debt"
    if d_reserves < 0 or d_debt > 0:
        assert total_reserves >= debt, "Reserves too small"
    u = (debt * WAD // total_reserves) if total_reserves > 0 else 0
    return min(u, WAD)


def calculate_rate(params, u: int, r0: int, shift: int = 0) -> int:
    """Replicates `_calculate_rate` given already-computed utilization `u`.

    `params` is the (u_inf, A, r_minf) triple from `get_params`; `shift` is the
    caller-supplied rate shift (stored separately in the contract), defaulting to
    0 for the common no-shift curve.
    """
    u_inf, A, r_minf = params
    a = tdiv(r0 * r_minf, WAD)
    b = A * r0 // (u_inf - u)
    rate = a + b + shift
    # Mirror the contract: clamp a (unreachable) sub-zero rate to 0 instead of reverting.
    return max(rate, 0)
