# @version 0.3.10
"""
@title SemiLog monetary policy
@notice Monetary policy to calculate borrow rates in lending markets depending on utilization.
        Unlike "core" policies, it does not depend on crvUSD price.
        Calculated as:
        log(rate) = utilization * (log(rate_max) - log(rate_min)) + log(rate_min)
        e.g.
        rate = rate_min * (rate_max / rate_min)**utilization
@author Curve.fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
"""
from vyper.interfaces import ERC20


interface Controller:
    def total_debt() -> uint256: view

interface Factory:
    def admin() -> address: view


event SetAdmin:
    admin: address

event SetRates:
    min_rate: uint256
    max_rate: uint256


MAX_EXP: constant(uint256) = 1000 * 10**18
MIN_RATE: public(constant(uint256)) = 10**15 / (365 * 86400)  # 0.1%
MAX_RATE: public(constant(uint256)) = 10**19 / (365 * 86400)  # 1000%

BORROWED_TOKEN: public(immutable(ERC20))

admin: public(address)

min_rate: public(uint256)
max_rate: public(uint256)
log_min_rate: public(int256)
log_max_rate: public(int256)


@external
def __init__(borrowed_token: ERC20, min_rate: uint256, max_rate: uint256):
    assert min_rate >= MIN_RATE and max_rate >= MIN_RATE\
        and min_rate <= MAX_RATE and max_rate <= MAX_RATE\
        and min_rate <= max_rate, "Wrong rates"

    BORROWED_TOKEN = borrowed_token
    self.min_rate = min_rate
    self.max_rate = max_rate
    self.log_min_rate = self.ln_int(min_rate)
    self.log_max_rate = self.ln_int(max_rate)

    self.admin = Factory(msg.sender).admin()


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
    res: uint256 = 0
    for i in range(8):
        t: uint256 = 2**(7 - i)
        p: uint256 = 2**t
        if x >= p * 10**18:
            x /= p
            res += t * 10**18
    d: uint256 = 10**18
    for i in range(59):  # 18 decimals: math.log2(10**10) == 59.7
        if (x >= 2 * 10**18):
            res += d
            x /= 2
        x = x * x / 10**18
        d /= 2
    # Now res = log2(x)
    # ln(x) = log2(x) / log2(e)
    return convert(res * 10**18 / 1442695040888963328, int256)
### END MATH ###


@internal
@view
def calculate_rate(_for: address) -> uint256:
    total_debt: uint256 = Controller(_for).total_debt()
    if total_debt == 0:
        return self.min_rate
    else:
        utilization: int256 = convert(total_debt * 10**18 / (BORROWED_TOKEN.balanceOf(_for) + total_debt), int256)
        log_min_rate: int256 = self.log_min_rate
        log_max_rate: int256 = self.log_max_rate
        return self.exp(utilization * (log_max_rate - log_min_rate) + log_min_rate)


@view
@external
def rate(_for: address = msg.sender) -> uint256:
    return self.calculate_rate(_for)


@external
def rate_write(_for: address = msg.sender) -> uint256:
    return self.calculate_rate(_for)


@external
def set_default_rates(min_rate: uint256, max_rate: uint256):
    assert msg.sender == self.admin

    assert min_rate >= MIN_RATE
    assert max_rate >= MIN_RATE
    assert min_rate <= MAX_RATE
    assert max_rate <= MAX_RATE
    assert max_rate >= min_rate

    self.min_rate = min_rate
    self.max_rate = max_rate
    self.log_min_rate = self.ln_int(min_rate)
    self.log_max_rate = self.ln_int(max_rate)

    log SetRates(min_rate, max_rate)


@external
def set_admin(admin: address):
    """
    @notice Set admin of the factory (should end up with DAO)
    @param admin Address of the admin
    """
    assert msg.sender == self.admin
    self.admin = admin
    log SetAdmin(admin)
