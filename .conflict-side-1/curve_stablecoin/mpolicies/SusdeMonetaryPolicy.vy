# @version 0.3.10
"""
@title SusdeMonetaryPolicy
@notice Based on SecondaryMonetaryPolicy, however following EMA of sUSDe yield rate
@author Curve.fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
"""
from vyper.interfaces import ERC20


interface EthenaVault:
    def totalAssets() -> uint256: view
    def vestingAmount() -> uint256: view
    def lastDistributionTimestamp() -> uint256: view

interface Controller:
    def total_debt() -> uint256: view

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

VESTING_PERIOD: public(constant(uint256)) = 8 * 3600
TEXP: public(constant(uint256)) = 200_000

BORROWED_TOKEN: public(immutable(ERC20))
FACTORY: public(immutable(Factory))
SUSDE: public(immutable(EthenaVault))

parameters: public(Parameters)
prev_ma_susde_rate: uint256
prev_susde_rate: uint256
last_timestamp: uint256


@external
def __init__(factory: Factory, susde: EthenaVault, borrowed_token: ERC20,
             target_utilization: uint256, low_ratio: uint256, high_ratio: uint256, rate_shift: uint256):
    """
    @param factory Factory contract
    @param susde SUSDE contract (vault)
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
    SUSDE = susde
    BORROWED_TOKEN = borrowed_token

    r: uint256 = self.raw_susde_rate()
    self.prev_susde_rate = r
    self.prev_ma_susde_rate = r
    self.last_timestamp = block.timestamp

    p: Parameters = self.get_params(target_utilization, low_ratio, high_ratio, rate_shift)
    self.parameters = p
    log SetParameters(p.u_inf, p.A, p.r_minf, p.shift)


@internal
@pure
def exp(power: int256) -> uint256:
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
def raw_susde_rate() -> uint256:
    assets: uint256 = SUSDE.totalAssets()
    if assets > 0:
        return SUSDE.vestingAmount() * 10**18 / (SUSDE.totalAssets() * VESTING_PERIOD)
    else:
        return 0


@external
@view
def raw_susde_apr() -> uint256:
    return self.raw_susde_rate() * (365 * 86400)


@internal
@view
def ema_susde_rate() -> uint256:
    last_timestamp: uint256 = self.last_timestamp
    if last_timestamp == block.timestamp:
        return self.prev_ma_susde_rate
    else:
        alpha: uint256 = self.exp(- convert((block.timestamp - last_timestamp) * (10**18 / TEXP), int256))
        return (self.prev_susde_rate * (10**18 - alpha) + self.prev_ma_susde_rate * alpha) / 10**18


@external
@view
def ma_susde_rate() -> uint256:
    return self.ema_susde_rate()


@internal
def ema_susde_rate_w() -> uint256:
    r: uint256 = self.ema_susde_rate()
    self.prev_ma_susde_rate = r
    if SUSDE.lastDistributionTimestamp() > self.last_timestamp:
        self.prev_susde_rate = self.raw_susde_rate()
    self.last_timestamp = block.timestamp
    return r


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
def calculate_rate(_for: address, d_reserves: int256, d_debt: int256, r0: uint256) -> uint256:
    p: Parameters = self.parameters
    total_debt: int256 = convert(Controller(_for).total_debt(), int256)
    total_reserves: int256 = convert(BORROWED_TOKEN.balanceOf(_for), int256) + total_debt + d_reserves
    total_debt += d_debt
    assert total_debt >= 0, "Negative debt"
    assert total_reserves >= total_debt, "Reserves too small"

    u: uint256 = 0
    if total_reserves > 0:
        u = convert(total_debt * 10**18  / total_reserves, uint256)

    return r0 * p.r_minf / 10**18 + p.A * r0 / (p.u_inf - u) + p.shift


@view
@external
def rate(_for: address = msg.sender) -> uint256:
    return self.calculate_rate(_for, 0, 0, self.ema_susde_rate())


@external
def rate_write(_for: address = msg.sender) -> uint256:
    return self.calculate_rate(_for, 0, 0, self.ema_susde_rate_w())


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
    return self.calculate_rate(_for, d_reserves, d_debt, self.ema_susde_rate())
