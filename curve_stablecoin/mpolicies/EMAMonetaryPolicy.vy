# @version 0.3.10
"""
@title EMAMonetaryPolicy
@notice Monetary Policy that follows EMA of external rate calculator contract's yield rate
        The external contract should return the rate per second
        For use with yieldbearing assets in like-kind lend markets (e.g. sfrxUSD/crvUSD)
@author Curve.fi
"""

from vyper.interfaces import ERC20


interface IRateCalculator:
    def rate() -> uint256: view

interface IController:
    def total_debt() -> uint256: view

interface IFactory:
    def admin() -> address: view


event SetParameters:
    u_inf: uint256
    A: uint256
    r_minf: int256
    shift: uint256


struct Parameters:
    u_inf: uint256
    A: uint256
    r_minf: int256
    shift: uint256


MIN_UTIL: constant(uint256) = 10**16
MAX_UTIL: constant(uint256) = 99 * 10**16
MIN_LOW_RATIO: constant(uint256) = 10**16
MAX_HIGH_RATIO: constant(uint256) = 100 * 10**18
MAX_RATE_SHIFT: constant(uint256) = 100 * 10**18
MIN_EMA_RATE: constant(uint256) = 317097920 # 1% APR

TEXP: public(constant(uint256)) = 40000

BORROWED_TOKEN: public(immutable(ERC20))
FACTORY: public(immutable(IFactory))
RATE_CALCULATOR: public(immutable(IRateCalculator))

parameters: public(Parameters)
prev_ma_rate: uint256
prev_rate: uint256
last_timestamp: uint256


@external
def __init__(
    factory: IFactory,
    rate_calculator: IRateCalculator,
    borrowed_token: ERC20,
    target_utilization: uint256,
    low_ratio: uint256,
    high_ratio: uint256,
    rate_shift: uint256
):
    """
    @param factory Address of the market's factory contract (for access control)
    @param rate_calculator Address of the external rate calculator (e.g. for sfrxUSD)
    @param borrowed_token ERC20 token being borrowed (e.g. crvUSD)
    @param target_utilization Utilization (0–1e18) where borrow rate equals base rate
    @param low_ratio Multiplier on base rate at 0% utilization (≥1e16)
    @param high_ratio Multiplier on base rate at 100% utilization (≤100e18)
    @param rate_shift Flat shift to apply to the resulting rate curve (can be 0)
    @notice Initializes the monetary policy with given parameters and sets initial EMA rate
    """
    assert target_utilization >= MIN_UTIL, "target_utilization too low"
    assert target_utilization <= MAX_UTIL, "target_utilization too high"
    assert low_ratio >= MIN_LOW_RATIO, "low_ratio too low"
    assert high_ratio <= MAX_HIGH_RATIO, "high_ratio too high"
    assert low_ratio < high_ratio, "low_ratio must be less than high_ratio"
    assert rate_shift <= MAX_RATE_SHIFT, "rate_shift too high"

    FACTORY = factory
    RATE_CALCULATOR = rate_calculator
    BORROWED_TOKEN = borrowed_token

    r: uint256 = rate_calculator.rate()
    self.prev_rate = r
    self.prev_ma_rate = r
    self.last_timestamp = block.timestamp

    p: Parameters = self.get_params(target_utilization, low_ratio, high_ratio, rate_shift)
    self.parameters = p
    log SetParameters(p.u_inf, p.A, p.r_minf, p.shift)


@internal
@pure
def exp(power: int256) -> uint256:
    """
    @notice Exponential approximation used for EMA calculation
    @param power Exponent scaled by 1e18
    @return exp_result Approximated exponential value
    """
    if power <= -41446531673892821376:
        return 0

    if power >= 135305999368893231589:
        raise "exp overflow"

    x: int256 = unsafe_div(unsafe_mul(power, 2**96), 10**18)

    k: int256 = unsafe_div(
        unsafe_add(
            unsafe_div(unsafe_mul(x, 2**96), 54916777467707473351141471128),
            2**95),
        2**96)
    x = unsafe_sub(x, unsafe_mul(k, 54916777467707473351141471128))

    y: int256 = unsafe_add(x, 1346386616545796478920950773328)
    y = unsafe_add(unsafe_div(unsafe_mul(y, x), 2**96), 57155421227552351082224309758442)
    p: int256 = unsafe_sub(unsafe_add(y, x), 94201549194550492254356042504812)
    p = unsafe_add(unsafe_div(unsafe_mul(p, y), 2**96), 28719021644029726153956944680412240)
    p = unsafe_add(unsafe_mul(p, x), (4385272521454847904659076985693276 * 2**96))

    q: int256 = x - 2855989394907223263936484059900
    q = unsafe_add(unsafe_div(unsafe_mul(q, x), 2**96), 50020603652535783019961831881945)
    q = unsafe_sub(unsafe_div(unsafe_mul(q, x), 2**96), 533845033583426703283633433725380)
    q = unsafe_add(unsafe_div(unsafe_mul(q, x), 2**96), 3604857256930695427073651918091429)
    q = unsafe_sub(unsafe_div(unsafe_mul(q, x), 2**96), 14423608567350463180887372962807573)
    q = unsafe_add(unsafe_div(unsafe_mul(q, x), 2**96), 26449188498355588339934803723976023)

    return shift(
        unsafe_mul(convert(unsafe_div(p, q), uint256), 3822833074963236453042738258902158003155416615667),
        unsafe_sub(k, 195))


@internal
@view
def raw_underlying_rate() -> uint256:
    """
    @notice Read the current per-second rate from the external rate calculator
    @return rate Yield rate per second, scaled by 1e18
    """
    return RATE_CALCULATOR.rate()


@external
@view
def raw_underlying_apr() -> uint256:
    """
    @notice Annualized version of the raw per-second rate
    @return APR Estimate, scaled by 1e18
    """
    return self.raw_underlying_rate() * (365 * 86400)


@internal
@view
def ema_rate() -> uint256:
    """
    @notice Calculates exponential moving average of the base rate
    @return ema_rate EMA-smoothed rate, floored to minimum
    """
    last_timestamp: uint256 = self.last_timestamp
    ema: uint256 = self.prev_ma_rate
    if last_timestamp != block.timestamp:
        alpha: uint256 = self.exp(- convert((block.timestamp - last_timestamp) * (10**18 / TEXP), int256))
        ema = (self.prev_rate * (10**18 - alpha) + self.prev_ma_rate * alpha) / 10**18

    return max(ema, MIN_EMA_RATE)


@external
@view
def ma_rate() -> uint256:
    """
    @notice View function to get EMA-smoothed rate
    @return ema_rate The smoothed rate
    """
    return self.ema_rate()


@internal
def ema_rate_w() -> uint256:
    """
    @notice Write variant of EMA function — updates stored EMA and raw rates
    @dev Catches reverts from rate calculator and sets fallback rate
    @return ema_rate Updated EMA rate, floored to minimum
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
    if success:
        r = convert(raw_result, uint256)

    if self.last_timestamp != block.timestamp:
        self.prev_rate = r
        ema: uint256 = self.ema_rate()
        self.prev_ma_rate = ema
        self.last_timestamp = block.timestamp
        return ema
    else:
        return self.prev_ma_rate


@internal
@pure
def get_params(u_0: uint256, alpha: uint256, beta: uint256, rate_shift: uint256) -> Parameters:
    """
    @notice Computes the internal rate curve parameters
    @param u_0 Target utilization
    @param alpha Low-end ratio
    @param beta High-end ratio
    @param rate_shift Constant shift on output
    @return p Struct containing computed parameters
    """
    p: Parameters = empty(Parameters)
    p.u_inf = (beta - 10**18) * u_0 / (((beta - 10**18) * u_0 - (10**18 - u_0) * (10**18 - alpha)) / 10**18)
    p.A = (10**18 - alpha) * p.u_inf / 10**18 * (p.u_inf - u_0) / u_0
    p.r_minf = convert(alpha, int256) - convert(p.A * 10**18 / p.u_inf, int256)
    p.shift = rate_shift
    return p


@internal
@view
def calculate_rate(_for: address, d_reserves: int256, d_debt: int256, r0: uint256) -> uint256:
    """
    @notice Computes dynamic interest rate based on utilization
    @param _for Address of market controller
    @param d_reserves Change in reserves (simulated)
    @param d_debt Change in debt (simulated)
    @param r0 Base rate (e.g., EMA rate)
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

    a: int256 = convert(r0, int256) * p.r_minf / 10**18
    b: int256 = convert(p.A * r0 / (p.u_inf - u), int256)
    rate_shift: int256 = convert(p.shift, int256)

    rate: int256 = a + b + rate_shift
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
    return self.calculate_rate(_for, 0, 0, self.ema_rate())


@external
def rate_write(_for: address = msg.sender) -> uint256:
    """
    @notice Updates EMA and returns current rate
    @param _for Address of the market controller
    @return rate Updated rate
    """
    return self.calculate_rate(_for, 0, 0, self.ema_rate_w())


@external
def set_parameters(
    target_utilization: uint256,
    low_ratio: uint256,
    high_ratio: uint256,
    rate_shift: uint256
):
    """
    @notice Admin function to change curve parameters
    @param target_utilization Target utilization where rate = base
    @param low_ratio Ratio of rate/base at 0% utilization
    @param high_ratio Ratio of rate/base at 100% utilization
    @param rate_shift Constant shift on the curve
    """
    assert msg.sender == FACTORY.admin(), "Not factory admin"
    assert target_utilization >= MIN_UTIL, "target_utilization too low"
    assert target_utilization <= MAX_UTIL, "target_utilization too high"
    assert low_ratio >= MIN_LOW_RATIO, "low_ratio too low"
    assert high_ratio <= MAX_HIGH_RATIO, "high_ratio too high"
    assert low_ratio < high_ratio, "low_ratio must be less than high_ratio"
    assert rate_shift <= MAX_RATE_SHIFT, "rate_shift too high"

    p: Parameters = self.get_params(target_utilization, low_ratio, high_ratio, rate_shift)
    self.parameters = p
    log SetParameters(p.u_inf, p.A, p.r_minf, p.shift)


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
    return self.calculate_rate(_for, d_reserves, d_debt, self.ema_rate())
