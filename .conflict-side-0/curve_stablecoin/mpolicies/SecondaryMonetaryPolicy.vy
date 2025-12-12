# @version 0.3.10
"""
@title Secondary monetary policy
@notice Monetary policy to calculate borrow rates in lending markets
        depending on "mint" borrow rate and utilization.

        Calculated as:

            rate = rate_from_amm * (r_minf + A / (u_inf - utilization))

        Depending on target utilization (u0), rate ratio at 0 (alpha) and  at max utilization (beta) one can calculate
        coefficients for the hyperbolic dependency:

            u_inf = (beta - 1) * u0 / ((beta - 1) * u0 - (1 - u0) * (1 - alpha))
            A = (1 - alpha) * (u_inf - u0) * u_inf / u0
            r_minf = alpha - A / u_inf

        The function reaches rate_from_amm at u0 utilization, alpha*rate_from_amm at 0 utilization and
        beta*rate_from_amm at 100% utilization.

@author Curve.fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
"""
from vyper.interfaces import ERC20


interface Controller:
    def total_debt() -> uint256: view

interface IAMM:
    def rate() -> uint256: view

interface Factory:
    def admin() -> address: view


event SetParameters:
    u_inf: uint256
    A: uint256
    r_minf: uint256
    shift: uint256

struct Parameters:
    u_inf: uint256
    A: uint256
    r_minf: uint256
    shift: uint256

MIN_UTIL: constant(uint256) = 10**16
MAX_UTIL: constant(uint256)  = 99 * 10**16
MIN_LOW_RATIO: constant(uint256)  = 10**16
MAX_HIGH_RATIO: constant(uint256) = 100 * 10**18
MAX_RATE_SHIFT: constant(uint256) = 100 * 10**18

BORROWED_TOKEN: public(immutable(ERC20))
FACTORY: public(immutable(Factory))
AMM: public(immutable(IAMM))

parameters: public(Parameters)


@external
def __init__(factory: Factory, amm: IAMM, borrowed_token: ERC20,
             target_utilization: uint256, low_ratio: uint256, high_ratio: uint256, rate_shift: uint256):
    """
    @param factory Factory contract
    @param amm AMM to take borrow rate from as a basis
    @param borrowed_token Borrowed token in the market (e.g. crvUSD)
    @param target_utilization Utilization at which borrow rate is the same as in AMM
    @param low_ratio Ratio rate/target_rate at 0% utilization
    @param high_ratio Ratio rate/target_rate at 100% utilization
    @param rate_shift Shift all the rate curve by this rate
    """
    assert target_utilization >= MIN_UTIL
    assert target_utilization <= MAX_UTIL
    assert low_ratio >= MIN_LOW_RATIO
    assert high_ratio <= MAX_HIGH_RATIO
    assert low_ratio < high_ratio
    assert rate_shift <= MAX_RATE_SHIFT

    FACTORY = factory
    AMM = amm
    BORROWED_TOKEN = borrowed_token
    p: Parameters = self.get_params(target_utilization, low_ratio, high_ratio, rate_shift)
    self.parameters = p
    log SetParameters(p.u_inf, p.A, p.r_minf, p.shift)


@internal
def get_params(u_0: uint256, alpha: uint256, beta: uint256, rate_shift: uint256) -> Parameters:
    p: Parameters = empty(Parameters)
    p.u_inf = (beta - 10**18) * u_0 / (((beta - 10**18) * u_0 - (10**18 - u_0) * (10**18 - alpha)) / 10**18)
    p.A = (10**18 - alpha) * p.u_inf / 10**18 * (p.u_inf - u_0) / u_0
    p.r_minf = alpha - p.A * 10**18 / p.u_inf
    p.shift = rate_shift
    return p


@internal
@view
def calculate_rate(_for: address, d_reserves: int256, d_debt: int256) -> uint256:
    p: Parameters = self.parameters
    total_debt: int256 = convert(Controller(_for).total_debt(), int256)
    total_reserves: int256 = convert(BORROWED_TOKEN.balanceOf(_for), int256) + total_debt + d_reserves
    total_debt += d_debt
    assert total_debt >= 0, "Negative debt"
    assert total_reserves >= total_debt, "Reserves too small"

    u: uint256 = 0
    if total_reserves > 0:
        u = convert(total_debt * 10**18  / total_reserves, uint256)
    r0: uint256 = AMM.rate()

    return r0 * p.r_minf / 10**18 + p.A * r0 / (p.u_inf - u) + p.shift


@view
@external
def rate(_for: address = msg.sender) -> uint256:
    return self.calculate_rate(_for, 0, 0)


@external
def rate_write(_for: address = msg.sender) -> uint256:
    return self.calculate_rate(_for, 0, 0)


@external
def set_parameters(target_utilization: uint256, low_ratio: uint256, high_ratio: uint256, rate_shift: uint256):
    """
    @param target_utilization Utilization at which borrow rate is the same as in AMM
    @param low_ratio Ratio rate/target_rate at 0% utilization
    @param high_ratio Ratio rate/target_rate at 100% utilization
    @param rate_shift Shift all the rate curve by this rate
    """
    assert msg.sender == FACTORY.admin()

    assert target_utilization >= MIN_UTIL
    assert target_utilization <= MAX_UTIL
    assert low_ratio >= MIN_LOW_RATIO
    assert high_ratio <= MAX_HIGH_RATIO
    assert low_ratio < high_ratio
    assert rate_shift <= MAX_RATE_SHIFT

    p: Parameters = self.get_params(target_utilization, low_ratio, high_ratio, rate_shift)
    self.parameters = p
    log SetParameters(p.u_inf, p.A, p.r_minf, p.shift)


@view
@external
def future_rate(_for: address, d_reserves: int256, d_debt: int256) -> uint256:
    return self.calculate_rate(_for, d_reserves, d_debt)
