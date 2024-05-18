# @version 0.3.10
"""
@title Secondary monetary policy
@notice Monetary policy to calculate borrow rates in lending markets
        depending on "mint" borrow rate and utilization.

        Calculated as:
        log(rate) = (utilization - target_utilization) * log(min_max_ratio) + log(rate_from_amm)

        For example, if target_utilization = 80%, rate is equal to rate_from_amm when system reaches it,
        and min_max_ratio is ratio of borrow rates between utilization=0% and utilization=100%

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
    min_max_ratio: uint256
    target_utilization: int256


MAX_EXP: constant(uint256) = 1000 * 10**18
MAX_RATIO: public(constant(uint256)) = 100 * 10**18

BORROWED_TOKEN: public(immutable(ERC20))
FACTORY: public(immutable(Factory))
AMM: public(immutable(IAMM))

min_max_ratio: public(uint256)
log_min_max_ratio: public(int256)
target_utilization: public(int256)


@external
def __init__(amm: IAMM, borrowed_token: ERC20, min_max_ratio: uint256, target_utilization: int256):
    """
    @param amm AMM to take borrow rate from as a basis
    @param borrowed_token Borrowed token in the market (e.g. crvUSD)
    @param min_max_ratio Ratio of borrow rates at 100% and 0% utilizations, multiplied by 1e18
    @param target_utilization Utilization at which borrow rate is the same as in AMM
    """
    assert min_max_ratio >= 10**18
    assert min_max_ratio <= MAX_RATIO
    assert target_utilization >= 0
    assert target_utilization <= 10**18

    FACTORY = Factory(msg.sender)
    AMM = amm
    BORROWED_TOKEN = borrowed_token
    self.min_max_ratio = min_max_ratio
    self.log_min_max_ratio = self.ln_int(min_max_ratio)
    self.target_utilization = target_utilization


### MATH ###
@internal
@pure
def exp(power: int256) -> uint256:
    if power <= -41446531673892821376:
        return 0

    if power >= 135305999368893231589:
        # Return MAX_EXP when we are in overflow mode
        return MAX_EXP

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
@pure
def ln_int(_x: uint256) -> int256:
    """
    @notice Logarithm ln() function based on log2. Not very gas-efficient but brief
    """
    # adapted from: https://medium.com/coinmonks/9aef8515136e
    # and vyper log implementation
    # This can be much more optimal but that's not important here
    x: uint256 = _x
    if _x < 10**18:
        x = 10**36 / _x
    res: uint256 = 0
    for i in range(8):
        t: uint256 = 2**(7 - i)
        p: uint256 = 2**t
        if x >= p * 10**18:
            x /= p
            res += t * 10**18
    d: uint256 = 10**18
    for i in range(59):  # 18 decimals: math.log2(10**18) == 59.7
        if (x >= 2 * 10**18):
            res += d
            x /= 2
        x = x * x / 10**18
        d /= 2
    # Now res = log2(x)
    # ln(x) = log2(x) / log2(e)
    result: int256 = convert(res * 10**18 / 1442695040888963328, int256)
    if _x >= 10**18:
        return result
    else:
        return -result
### END MATH ###


@internal
@view
def calculate_rate(_for: address, d_reserves: int256, d_debt: int256) -> uint256:
    log_amm_rate: int256 = self.ln_int(AMM.rate())
    total_debt: int256 = convert(Controller(_for).total_debt(), int256)
    total_reserves: int256 = convert(BORROWED_TOKEN.balanceOf(_for), int256) + total_debt + d_reserves
    total_debt += d_debt
    assert total_debt >= 0, "Negative debt"
    assert total_reserves >= total_debt, "Reserves too small"

    return self.exp((total_debt - total_reserves * self.target_utilization / 10**18) * self.log_min_max_ratio / total_reserves + log_amm_rate)


@view
@external
def rate(_for: address = msg.sender) -> uint256:
    return self.calculate_rate(_for, 0, 0)


@external
def rate_write(_for: address = msg.sender) -> uint256:
    return self.calculate_rate(_for, 0, 0)


@external
def set_parameters(min_max_ratio: uint256, target_utilization: int256):
    assert msg.sender == FACTORY.admin()

    assert min_max_ratio >= 10**18
    assert min_max_ratio <= MAX_RATIO
    assert target_utilization >= 0
    assert target_utilization <= 10**18

    if min_max_ratio != self.min_max_ratio:
        self.min_max_ratio = min_max_ratio
        self.log_min_max_ratio = self.ln_int(min_max_ratio)
    if target_utilization != self.target_utilization:
        self.target_utilization = target_utilization

    log SetParameters(min_max_ratio, target_utilization)


@view
@external
def future_rate(_for: address, d_reserves: int256, d_debt: int256) -> uint256:
    return self.calculate_rate(_for, d_reserves, d_debt)
