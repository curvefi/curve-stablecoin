#pragma version 0.4.3

"""
@title Hyperbolic Monetary Policy With Dynamic Rate
@author Curve.Finance
@license Copyright (c) Curve.Finance, 2020-2026 - all rights reserved
@notice Monetary Policy that follows EMA of external rate calculator contract's yield rate.
        The external contract should return the rate per second.
        For use with yield-bearing assets in like-kind lend markets (e.g. sfrxUSD/crvUSD).
"""

from curve_std import ema
from curve_stablecoin import constants as c
from curve_stablecoin.interfaces import IController
from curve_stablecoin.interfaces import IHyperbolicDynamicMP
from curve_stablecoin.interfaces import IRateCalculator

implements: IHyperbolicDynamicMP
initializes: ema


WAD: constant(uint256) = c.WAD
SWAD: constant(int256) = c.SWAD

MIN_TARGET_UTIL: constant(uint256) = WAD // 100
MAX_TARGET_UTIL: constant(uint256) = 99 * WAD // 100
MIN_LOW_RATIO: constant(uint256) = WAD // 100
MAX_HIGH_RATIO: constant(uint256) = 100 * WAD
MAX_RATE_SHIFT: constant(uint256) = 100 * WAD
MIN_TARGET_RATE: constant(uint256) = 317097920        # ~1% APR
MAX_TARGET_RATE: constant(uint256) = 47564687975      # ~150% APR

TEXP: public(constant(uint256)) = 40000

CONTROLLER: public(immutable(IController))
RATE_CALCULATOR: public(immutable(IRateCalculator))

parameters: public(IHyperbolicDynamicMP.Parameters)

# Identifier of the EMA tracking the rate calculator's per-second yield rate.
TARGET_RATE_EMA_ID: constant(String[4]) = "rate"


@deploy
def __init__(
    _controller: IController,
    _rate_calculator: IRateCalculator,
    _target_utilization: uint256,
    _low_ratio: uint256,
    _high_ratio: uint256,
    _rate_shift: uint256
):
    """
    @notice Initializes the monetary policy with given parameters and sets initial EMA rate
    @param _controller Address of the market's controller contract (for access control)
    @param _rate_calculator Address of the external rate calculator (e.g. for sfrxUSD)
    @param _target_utilization Utilization (0–1e18) where borrow rate equals base rate
    @param _low_ratio Multiplier on base rate at 0% utilization (≥1e16)
    @param _high_ratio Multiplier on base rate at 100% utilization (≤100e18)
    @param _rate_shift Flat shift to apply to the resulting rate curve (can be 0)
    """
    CONTROLLER = _controller
    RATE_CALCULATOR = _rate_calculator

    ema.__init__(
        [
            ema.EMAConfig(
                ema_id=TARGET_RATE_EMA_ID,
                initial_value=staticcall _rate_calculator.rate(),
                ema_time=TEXP,
            )
        ]
    )

    self._set_parameters(_target_utilization, _low_ratio, _high_ratio, _rate_shift)


@external
@view
def raw_underlying_rate() -> uint256:
    """
    @notice Read the current per-second rate from the external rate calculator
    @return rate Yield rate per second, scaled by 1e18
    """
    return staticcall RATE_CALCULATOR.rate()


@external
@view
def raw_underlying_apr() -> uint256:
    """
    @notice Annualized version of the raw per-second rate
    @return APR Estimate, scaled by 1e18
    """
    return (staticcall RATE_CALCULATOR.rate()) * (365 * 86400)


@internal
@view
def _target_rate() -> uint256:
    """
    @notice Reads the EMA-smoothed base rate
    @return ema_rate EMA-smoothed rate, clamped to [MIN_TARGET_RATE, MAX_TARGET_RATE]
    """
    return min(max(ema.read(TARGET_RATE_EMA_ID), MIN_TARGET_RATE), MAX_TARGET_RATE)


@external
@view
def target_rate() -> uint256:
    """
    @notice View function to get EMA-smoothed rate per-second
    @return ema_rate The smoothed rate
    """
    return self._target_rate()


@external
@view
def target_apr() -> uint256:
    """
    @notice View function to get annualized EMA-smoothed rate (APR)
    @return ema_apr The smoothed rate annualized
    """
    return self._target_rate() * (365 * 86400)


@internal
def _target_rate_w() -> uint256:
    """
    @notice Write variant of EMA function — updates and returns the stored EMA rate
    @dev If the rate calculator call reverts, updates the EMA with a fallback rate of 0
    @return ema_rate Updated EMA rate, clamped to [MIN_TARGET_RATE, MAX_TARGET_RATE]
    """
    raw_result: Bytes[32] = empty(Bytes[32])
    success: bool = False

    success, raw_result = raw_call(
        RATE_CALCULATOR.address,
        method_id("rate()"),
        max_outsize=32,
        is_static_call=True,
        revert_on_failure=False
    )

    r: uint256 = 0
    if success and len(raw_result) > 0:
        r = convert(raw_result, uint256)

    return min(max(ema.update(TARGET_RATE_EMA_ID, r), MIN_TARGET_RATE), MAX_TARGET_RATE)


@internal
@pure
def _get_params(_u_0: uint256, _alpha: uint256, _beta: uint256, _rate_shift: uint256) -> IHyperbolicDynamicMP.Parameters:
    """
    @notice Computes the internal rate curve parameters
    @param _u_0 Target utilization
    @param _alpha Low-end ratio
    @param _beta High-end ratio
    @return p Struct containing computed parameters (shift is set by the caller)
    """
    p: IHyperbolicDynamicMP.Parameters = empty(IHyperbolicDynamicMP.Parameters)

    numerator: uint256 = (_beta - WAD) * _u_0
    subtrahend: uint256 = (WAD - _u_0) * (WAD - _alpha)
    # We need numerator >= subtrahend + WAD, not just numerator > subtrahend
    # to prevent A and r_minf computations overflow.
    assert numerator >= subtrahend + WAD, "invalid curve"

    p.u_inf = numerator * WAD // (numerator - subtrahend)
    # u_inf is the rate curve's utilization asymptote; it must sit strictly above
    # 100%, else the rate diverges (and p.u_inf - u underflows) as u approaches WAD.
    # Integer flooring can collapse u_inf to exactly WAD even when inner >= WAD.
    assert p.u_inf > WAD, "u_inf <= 100%"
    p.A = (WAD - _alpha) * p.u_inf // WAD * (p.u_inf - _u_0) // _u_0
    p.r_minf = convert(_alpha, int256) - convert(p.A * WAD // p.u_inf, int256)
    p.target_utilization = _u_0
    p.low_ratio = _alpha
    p.high_ratio = _beta
    p.rate_shift = _rate_shift
    return p


@internal
def _set_parameters(
    _target_utilization: uint256,
    _low_ratio: uint256,
    _high_ratio: uint256,
    _rate_shift: uint256
):
    """
    @notice Validates, computes and stores the rate curve parameters
    @dev Shared by the constructor and set_parameters; performs no access control
    @param _target_utilization Target utilization where rate = base
    @param _low_ratio Ratio of rate/base at 0% utilization
    @param _high_ratio Ratio of rate/base at 100% utilization
    @param _rate_shift Constant shift on the curve
    """
    assert _target_utilization >= MIN_TARGET_UTIL, "target_utilization too low"
    assert _target_utilization <= MAX_TARGET_UTIL, "target_utilization too high"
    assert _low_ratio >= MIN_LOW_RATIO, "low_ratio too low"
    assert _low_ratio < WAD, "low_ratio too high"
    assert _high_ratio > WAD, "high_ratio too low"
    assert _high_ratio <= MAX_HIGH_RATIO, "high_ratio too high"
    assert _rate_shift <= MAX_RATE_SHIFT, "rate_shift too high"

    p: IHyperbolicDynamicMP.Parameters = self._get_params(_target_utilization, _low_ratio, _high_ratio, _rate_shift)
    self.parameters = p

    log IHyperbolicDynamicMP.SetParameters(
        u_inf=p.u_inf,
        A=p.A,
        r_minf=p.r_minf,
        target_utilization=p.target_utilization,
        low_ratio=p.low_ratio,
        high_ratio=p.high_ratio,
        rate_shift=p.rate_shift,
    )


@internal
@view
def _get_utilization(_d_reserves: int256, _d_debt: int256) -> uint256:
    """
    @notice Computes market utilization under simulated reserve/debt changes
    @param _d_reserves Change in reserves (simulated)
    @param _d_debt Change in debt (simulated)
    @return u Utilization ratio (total_debt / total_reserves), scaled by 1e18
    """
    total_debt: int256 = convert(staticcall CONTROLLER.total_debt(), int256)
    total_reserves: int256 = (
        convert(staticcall CONTROLLER.available_balance(), int256)
        + total_debt
        - convert(staticcall CONTROLLER.admin_fees(), int256)
        + _d_reserves
    )
    total_debt += _d_debt
    assert total_debt >= 0, "Negative debt"
    assert total_reserves >= total_debt, "Reserves too small"

    u: uint256 = 0
    if total_reserves > 0:
        u = convert(total_debt * SWAD // total_reserves, uint256)

    return u


@internal
@view
def _calculate_rate(_d_reserves: int256, _d_debt: int256, _r0: uint256) -> uint256:
    """
    @notice Computes dynamic interest rate based on utilization
    @param _d_reserves Change in reserves (simulated)
    @param _d_debt Change in debt (simulated)
    @param _r0 Base rate (e.g., EMA rate)
    @return rate Final rate based on utilization
    """
    p: IHyperbolicDynamicMP.Parameters = self.parameters
    u: uint256 = self._get_utilization(_d_reserves, _d_debt)
    a: int256 = convert(_r0, int256) * p.r_minf // SWAD
    b: int256 = convert(p.A * _r0 // (p.u_inf - u), int256)
    rate_shift: int256 = convert(p.rate_shift, int256)
    rate: int256 = a + b + rate_shift
    assert rate >= 0, "Negative rate"

    return convert(rate, uint256)


@view
@external
def rate() -> uint256:
    """
    @notice View function to compute the current borrow rate
    @return rate Computed interest rate
    """
    return self._calculate_rate(0, 0, self._target_rate())


@external
def rate_write() -> uint256:
    """
    @notice Updates EMA and returns current rate
    @return rate Updated rate
    """
    assert CONTROLLER.address == msg.sender, "Controller only"
    return self._calculate_rate(0, 0, self._target_rate_w())


@external
def set_parameters(
    _target_utilization: uint256,
    _low_ratio: uint256,
    _high_ratio: uint256,
    _rate_shift: uint256
):
    """
    @notice Admin function to change curve parameters
    @param _target_utilization Target utilization where rate = base
    @param _low_ratio Ratio of rate/base at 0% utilization
    @param _high_ratio Ratio of rate/base at 100% utilization
    @param _rate_shift Constant shift on the curve
    """
    assert msg.sender == staticcall (staticcall CONTROLLER.factory()).admin(), "Not factory admin"

    self._set_parameters(_target_utilization, _low_ratio, _high_ratio, _rate_shift)


@view
@external
def future_rate(_d_reserves: int256, _d_debt: int256) -> uint256:
    """
    @notice View function to estimate future rate under reserve/debt changes
    @param _d_reserves Simulated reserve change
    @param _d_debt Simulated debt change
    @return rate Estimated future rate
    """
    return self._calculate_rate(_d_reserves, _d_debt, self._target_rate())
