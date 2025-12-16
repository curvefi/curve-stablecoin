# @version 0.3.10
"""
@title KinkedMonetaryPolicy
@notice Interest rate model with a kinked curve based on utilization.
         Used for non-yielding markets (e.g. WBTC/crvUSD) where borrow
         rates are determined purely by market utilization.
"""

from vyper.interfaces import ERC20

interface IController:
    def total_debt() -> uint256: view

interface IFactory:
    def admin() -> address: view

event SetParameters:
    u_inf: uint256
    A: uint256
    r_minf: int256
    base: uint256

struct Parameters:
    u_inf: uint256
    A: uint256
    r_minf: int256
    base: uint256

MIN_UTIL: constant(uint256) = 10**16
MAX_UTIL: constant(uint256) = 99 * 10**16
MIN_LOW_RATIO: constant(uint256) = 10**16
MAX_HIGH_RATIO: constant(uint256) = 100 * 10**18

BORROWED_TOKEN: public(immutable(ERC20))
FACTORY: public(immutable(IFactory))
parameters: public(Parameters)

@external
def __init__(
    factory: IFactory,
    borrowed_token: ERC20,
    target_utilization: uint256,
    low_ratio: uint256,
    high_ratio: uint256,
    base_rate: uint256
):
    """
    @param factory Address of the market's factory contract (for access control)
    @param borrowed_token ERC20 token being borrowed (e.g. crvUSD)
    @param target_utilization Utilization (0–1e18) where borrow rate equals base rate
    @param low_ratio Multiplier on base rate at 0% utilization (≥1e16)
    @param high_ratio Multiplier on base rate at 100% utilization (≤100e18)
    @param base_rate Rate at target utilization
    @notice Initializes the monetary policy with given parameters
    """
    assert target_utilization >= MIN_UTIL
    assert target_utilization <= MAX_UTIL
    assert low_ratio >= MIN_LOW_RATIO
    assert high_ratio <= MAX_HIGH_RATIO
    assert low_ratio < high_ratio

    FACTORY = factory
    BORROWED_TOKEN = borrowed_token

    p: Parameters = self.get_params(target_utilization, low_ratio, high_ratio, base_rate)
    self.parameters = p
    log SetParameters(p.u_inf, p.A, p.r_minf, p.base)


@internal
def get_params(u_0: uint256, alpha: uint256, beta: uint256, base_rate: uint256) -> Parameters:
    """
    @notice Computes the internal rate curve parameters
    @param u_0 Target utilization
    @param alpha Low-end ratio
    @param beta High-end ratio
    @param base_rate Rate at target utilization
    @return p Struct containing computed parameters
    """
    p: Parameters = empty(Parameters)
    p.u_inf = (beta - 10**18) * u_0 / (((beta - 10**18) * u_0 - (10**18 - u_0) * (10**18 - alpha)) / 10**18)
    p.A = (10**18 - alpha) * p.u_inf / 10**18 * (p.u_inf - u_0) / u_0
    p.r_minf = convert(alpha, int256) - convert(p.A * 10**18 / p.u_inf, int256)
    p.base = base_rate / 31536000
    return p


@internal
@view
def calculate_rate(_for: address, d_reserves: int256, d_debt: int256) -> uint256:
    """
    @notice Computes interest rate based on utilization
    @param _for Address of market controller
    @param d_reserves Change in reserves (simulated)
    @param d_debt Change in debt (simulated)
    @return rate Final rate based on utilization
    """
    p: Parameters = self.parameters
    total_debt: int256 = convert(IController(_for).total_debt(), int256)
    total_reserves: int256 = convert(BORROWED_TOKEN.balanceOf(_for), int256) + total_debt + d_reserves
    total_debt += d_debt
    assert total_debt >= 0, "Negative debt"
    assert total_reserves >= total_debt, "Reserves too small"

    u: uint256 = 0
    if total_reserves > 0:
        u = convert(total_debt * 10**18 / total_reserves, uint256)

    a: int256 = convert(p.base, int256) * p.r_minf / 10**18
    b: int256 = convert(p.A * p.base / (p.u_inf - u), int256)

    rate: int256 = a + b
    assert rate >= 0, "Negative rate"
    return convert(rate, uint256)


@view
@external
def rate(_for: address = msg.sender) -> uint256:
    """
    @notice View function to compute the current borrow rate
    @param _for Address of the market controller
    @return rate Computed interest rate
    """
    return self.calculate_rate(_for, 0, 0)


@external
def rate_write(_for: address = msg.sender) -> uint256:
    """
    @notice Updates EMA and returns current rate
    @param _for Address of the market controller
    @return rate Updated rate
    """
    return self.calculate_rate(_for, 0, 0)


@external
def set_parameters(
    target_utilization: uint256,
    low_ratio: uint256,
    high_ratio: uint256,
    base_rate: uint256
):
    """
    @notice Admin function to change curve parameters
    @param target_utilization Target utilization where rate = base
    @param low_ratio Ratio of rate/base at 0% utilization
    @param high_ratio Ratio of rate/base at 100% utilization
    @param base_rate Rate at target utilization
    """
    assert msg.sender == FACTORY.admin()
    assert target_utilization >= MIN_UTIL
    assert target_utilization <= MAX_UTIL
    assert low_ratio >= MIN_LOW_RATIO
    assert high_ratio <= MAX_HIGH_RATIO
    assert low_ratio < high_ratio

    p: Parameters = self.get_params(target_utilization, low_ratio, high_ratio, base_rate)
    self.parameters = p
    log SetParameters(p.u_inf, p.A, p.r_minf, p.base)


@view
@external
def future_rate(_for: address, d_reserves: int256, d_debt: int256) -> uint256:
    """
    @notice View function to estimate future rate under reserve/debt changes
    @param _for Address of the controller
    @param d_reserves Simulated reserve change
    @param d_debt Simulated debt change
    @return rate Estimated future rate
    """
    return self.calculate_rate(_for, d_reserves, d_debt)
