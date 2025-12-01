# pragma version 0.4.3
"""
@title LLAMMA - crvUSD AMM
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
"""

# Glossary of variables and terms
# =======================
# * ticks, bands - price ranges where liquidity is deposited
# * x - coin which is being borrowed, typically stablecoin
# * y - collateral coin (for example, wETH)
# * A - amplification, the measure of how concentrated the tick is
# * rate - interest rate
# * rate_mul - rate multiplier, 1 + integral(rate * dt)
# * active_band - current band. Other bands are either in one or other coin, but not both
# * min_band - bands below this are definitely empty
# * max_band - bands above this are definitely empty
# * bands_x[n], bands_y[n] - amounts of coin x or y deposited in band n
# * user_shares[user,n] / total_shares[n] - fraction of n'th band owned by a user
# * p_oracle - external oracle price (can be from another AMM)
# * p (as in get_p) - current price of AMM. It depends not only on the balances (x,y) in the band and active_band, but
# also on p_oracle
# * p_current_up, p_current_down - the value of p at constant p_oracle when y=0 or x=0 respectively for the band n
# * p_oracle_up, p_oracle_down - edges of the band when p=p_oracle (steady state), happen when x=0 or y=0 respectively,
# for band n.
# * Grid of bands is set for p_oracle values such as:
#   * p_oracle_up(n) = base_price * ((A - 1) / A)**n
#   * p_oracle_down(n) = p_oracle_up(n) * (A - 1) / A = p_oracle_up(n+1)
# * p_current_up and p_oracle_up change in opposite directions with n
# * When intereste is accrued - all the grid moves by change of base_price
#
# Bonding curve reads as:
# (f + x) * (g + y) = Inv = p_oracle * A**2 * y0**2
# =======================

from curve_stablecoin.interfaces import IAMM
implements: IAMM

from curve_stablecoin.interfaces import IPriceOracle
from curve_stablecoin.interfaces import ILMGauge
from curve_std.interfaces import IERC20

from curve_std import math as crv_math

from snekmate.utils import math

from curve_stablecoin import constants as c

from curve_std import token as tkn


# https://github.com/vyperlang/vyper/issues/4723
WAD: constant(uint256) = c.WAD
MAX_TICKS: constant(int256) = c.MAX_TICKS
MAX_TICKS_UINT: constant(uint256) = c.MAX_TICKS_UINT
DEAD_SHARES: constant(uint256) = c.DEAD_SHARES
MAX_SKIP_TICKS: constant(int256) = c.MAX_SKIP_TICKS
MAX_SKIP_TICKS_UINT: constant(uint256) = c.MAX_SKIP_TICKS_UINT

BORROWED_TOKEN: immutable(IERC20)    # x
BORROWED_PRECISION: immutable(uint256)
COLLATERAL_TOKEN: immutable(IERC20)  # y
COLLATERAL_PRECISION: immutable(uint256)
BASE_PRICE: immutable(uint256)
admin: public(address)

A: public(immutable(uint256))
Aminus1: immutable(uint256)
A2: immutable(uint256)
Aminus12: immutable(uint256)
SQRT_BAND_RATIO: immutable(uint256)  # sqrt(A / (A - 1))
LOG_A_RATIO: immutable(int256)  # ln(A / (A - 1))
MAX_ORACLE_DN_POW: immutable(uint256)  # (A / (A - 1)) ** 50

fee: public(uint256)
rate: public(uint256)
rate_time: uint256
rate_mul: uint256
active_band: public(int256)
min_band: public(int256)
max_band: public(int256)

_price_oracle: IPriceOracle

# https://github.com/vyperlang/vyper/issues/4721
@view
@external
def price_oracle_contract() -> IPriceOracle:
    return self._price_oracle


old_p_o: uint256
old_dfee: uint256
prev_p_o_time: uint256
PREV_P_O_DELAY: constant(uint256) = 2 * 60  # s = 2 min
MAX_P_O_CHG: constant(uint256) = 12500 * 10**14  # <= 2**(1/3) - max relative change to have fee < 50%

bands_x: public(HashMap[int256, uint256])
bands_y: public(HashMap[int256, uint256])

total_shares: HashMap[int256, uint256]
user_shares: public(HashMap[address, IAMM.UserTicks])


_liquidity_mining_callback: ILMGauge

# https://github.com/vyperlang/vyper/issues/4721
@view
@external
def liquidity_mining_callback() -> ILMGauge:
    return self._liquidity_mining_callback


@deploy
def __init__(
        _borrowed_token: IERC20,
        _borrowed_precision: uint256,
        _collateral_token: IERC20,
        _collateral_precision: uint256,
        _A: uint256,
        _sqrt_band_ratio: uint256,
        _log_A_ratio: int256,
        _base_price: uint256,
        _fee: uint256,
        _admin_fee: uint256,
        _price_oracle: IPriceOracle,
    ):
    """
    @notice LLAMMA constructor
    @param _borrowed_token Token which is being borrowed
    @param _collateral_token Token used as collateral
    @param _collateral_precision Precision of collateral: we pass it because we want the blueprint to fit into bytecode
    @param _A "Amplification coefficient" which also defines density of liquidity and band size. Relative band size is 1/_A
    @param _sqrt_band_ratio Precomputed int(sqrt(A / (A - 1)) * 1e18)
    @param _log_A_ratio Precomputed int(ln(A / (A - 1)) * 1e18)
    @param _base_price Typically the initial crypto price at which AMM is deployed. Will correspond to band 0
    @param _fee Relative fee of the AMM: int(fee * 1e18)
    @param _admin_fee DEPRECATED, left for backward compatibility
    @param _price_oracle External price oracle which has price() and price_w() methods
           which both return current price of collateral multiplied by 1e18
    """
    BORROWED_TOKEN = _borrowed_token
    BORROWED_PRECISION = _borrowed_precision
    COLLATERAL_TOKEN = _collateral_token
    COLLATERAL_PRECISION = _collateral_precision
    A = _A
    BASE_PRICE = _base_price

    Aminus1 = unsafe_sub(A, 1)
    A2 = pow_mod256(A, 2)
    Aminus12 = pow_mod256(unsafe_sub(A, 1), 2)

    self.fee = _fee
    self._price_oracle = _price_oracle
    self.prev_p_o_time = block.timestamp
    self.old_p_o = staticcall self._price_oracle.price()

    self.rate_mul = 10**18

    # sqrt(A / (A - 1)) - needs to be pre-calculated externally
    SQRT_BAND_RATIO = _sqrt_band_ratio
    # log(A / (A - 1)) - needs to be pre-calculated externally
    LOG_A_RATIO = _log_A_ratio

    # (A / (A - 1)) ** 50
    # This is not gas-optimal but good with bytecode size and does not overflow
    pow: uint256 = 10**18
    for i: uint256 in range(50):
        pow = unsafe_div(pow * A, Aminus1)
    MAX_ORACLE_DN_POW = pow


@external
def set_admin(_admin: address):
    """
    @notice Set admin of the AMM. Typically it's a controller (unless it's tests)
    @param _admin Admin address
    """
    assert self.admin == empty(address)
    self.admin = _admin
    tkn.max_approve(BORROWED_TOKEN, _admin)
    tkn.max_approve(COLLATERAL_TOKEN, _admin)


@internal
@pure
def sqrt_int(_x: uint256) -> uint256:
    """
    @notice Wrapping isqrt builtin because otherwise it will be repeated every time instead of calling
    @param _x Square root's input in "normal" units, e.g. sqrt_int(1) == 1
    """
    return isqrt(_x)


@external
@view
def coins(i: uint256) -> address:
    return [BORROWED_TOKEN.address, COLLATERAL_TOKEN.address][i]


@internal
@view
def limit_p_o(p: uint256) -> uint256[2]:
    """
    @notice Limits oracle price to avoid losses at abrupt changes, as well as calculates a dynamic fee.
        If we consider oracle_change such as:
            ratio = p_new / p_old
        (let's take for simplicity p_new < p_old, otherwise we compute p_old / p_new)
        Then if the minimal AMM fee will be:
            fee = (1 - ratio**3),
        AMM will not have a loss associated with the price change.
        However, over time fee should still go down (over PREV_P_O_DELAY), and also ratio should be limited
        because we don't want the fee to become too large (say, 50%) which is achieved by limiting the instantaneous
        change in oracle price.

    @return (limited_price_oracle, dynamic_fee)
    """
    p_new: uint256 = p
    dt: uint256 = unsafe_sub(PREV_P_O_DELAY, min(PREV_P_O_DELAY, block.timestamp - self.prev_p_o_time))
    ratio: uint256 = 0

    # ratio = 1 - (p_o_min / p_o_max)**3

    if dt > 0:
        old_p_o: uint256 = self.old_p_o
        # ratio = p_o_min / p_o_max
        if p > old_p_o:
            ratio = unsafe_div(old_p_o * 10**18, p)
            if ratio < 10**36 // MAX_P_O_CHG:
                p_new = unsafe_div(old_p_o * MAX_P_O_CHG, 10**18)
                ratio = 10**36 // MAX_P_O_CHG
        else:
            ratio = unsafe_div(p * 10**18, old_p_o)
            if ratio < 10**36 // MAX_P_O_CHG:
                p_new = unsafe_div(old_p_o * 10**18, MAX_P_O_CHG)
                ratio = 10**36 // MAX_P_O_CHG

        # ratio is lower than 1e18
        # Also guaranteed to be limited, therefore can have all ops unsafe
        ratio = min(
            unsafe_div(
                unsafe_mul(
                    unsafe_sub(unsafe_add(10**18, self.old_dfee), unsafe_div(pow_mod256(ratio, 3), 10**36)),  # (f' + (1 - r**3))
                    dt),                                                                                  # * dt / T
            PREV_P_O_DELAY),
        10**18 - 1)

    return [p_new, ratio]


@internal
@view
def get_dynamic_fee(p_o: uint256, p_o_up: uint256) -> uint256:
    """
    Dynamic fee equal to a quarter of difference between current price and the price of price oracle
    """
    p_c_d: uint256 = unsafe_div(unsafe_div(p_o ** 2, p_o_up) * p_o, p_o_up)
    p_c_u: uint256 = unsafe_div(unsafe_div(p_c_d * A, Aminus1) * A, Aminus1)
    if p_o < p_c_d:
        return unsafe_div(unsafe_sub(p_c_d, p_o) * (10**18 // 4), p_c_d)
    elif p_o > p_c_u:
        return unsafe_div(unsafe_sub(p_o, p_c_u) * (10**18 // 4), p_o)
    else:
        return 0


@internal
@view
def _price_oracle_ro() -> uint256[2]:
    return self.limit_p_o(staticcall self._price_oracle.price())


@internal
def _price_oracle_w() -> uint256[2]:
    p: uint256[2] = self.limit_p_o(extcall self._price_oracle.price_w())
    self.prev_p_o_time = block.timestamp
    self.old_p_o = p[0]
    self.old_dfee = p[1]
    return p


@external
@view
def price_oracle() -> uint256:
    """
    @notice Value returned by the external price oracle contract
    """
    return self._price_oracle_ro()[0]


@external
@view
def dynamic_fee() -> uint256:
    """
    @notice Dynamic fee which accounts for price_oracle shifts
    """
    return max(self.fee, self._price_oracle_ro()[1])


@internal
@view
def _rate_mul() -> uint256:
    """
    @notice Rate multiplier which is 1.0 + integral(rate, dt)
    @return Rate multiplier in units where 1.0 == 1e18
    """
    return unsafe_div(self.rate_mul * (10**18 + self.rate * (block.timestamp - self.rate_time)), 10**18)


@external
@view
def get_rate_mul() -> uint256:
    """
    @notice Rate multiplier which is 1.0 + integral(rate, dt)
    @return Rate multiplier in units where 1.0 == 1e18
    """
    return self._rate_mul()


@internal
@view
def _base_price() -> uint256:
    """
    @notice Price which corresponds to band 0.
            Base price grows with time to account for interest rate (which is 0 by default)
    """
    return unsafe_div(BASE_PRICE * self._rate_mul(), 10**18)


@external
@view
def get_base_price() -> uint256:
    """
    @notice Price which corresponds to band 0.
            Base price grows with time to account for interest rate (which is 0 by default)
    """
    return self._base_price()


@internal
@view
def _p_oracle_up(n: int256) -> uint256:
    """
    @notice Upper oracle price for the band to have liquidity when p = p_oracle
    @param n Band number (can be negative)
    @return Price at 1e18 base
    """
    # p_oracle_up(n) = p_base * ((A - 1) / A) ** n
    # p_oracle_down(n) = p_base * ((A - 1) / A) ** (n + 1) = p_oracle_up(n+1)
    # return unsafe_div(self._base_price() * self.exp_int(-n * LOG_A_RATIO), 10**18)

    power: int256 = -n * LOG_A_RATIO

    # ((A - 1) / A) ** n = exp(-n * ln(A / (A - 1))) = exp(-n * LOG_A_RATIO)
    exp_result: uint256 = convert(math._wad_exp(power), uint256)

    assert exp_result > 1000  # dev: limit precision of the multiplier
    return unsafe_div(self._base_price() * exp_result, WAD)


@internal
@view
def _p_current_band(n: int256) -> uint256:
    """
    @notice Lowest possible price of the band at current oracle price
    @param n Band number (can be negative)
    @return Price at 1e18 base
    """
    # k = (self.A - 1) / self.A  # equal to (p_down / p_up)
    # p_base = self.p_base * k ** n = p_oracle_up(n)
    p_base: uint256 = self._p_oracle_up(n)

    # return self.p_oracle**3 / p_base**2
    p_oracle: uint256 = self._price_oracle_ro()[0]
    return unsafe_div(p_oracle**2 // p_base * p_oracle, p_base)


@external
@view
def p_current_up(n: int256) -> uint256:
    """
    @notice Highest possible price of the band at current oracle price
    @param n Band number (can be negative)
    @return Price at 1e18 base
    """
    return self._p_current_band(n + 1)


@external
@view
def p_current_down(n: int256) -> uint256:
    """
    @notice Lowest possible price of the band at current oracle price
    @param n Band number (can be negative)
    @return Price at 1e18 base
    """
    return self._p_current_band(n)


@external
@view
def p_oracle_up(n: int256) -> uint256:
    """
    @notice Highest oracle price for the band to have liquidity when p = p_oracle
    @param n Band number (can be negative)
    @return Price at 1e18 base
    """
    return self._p_oracle_up(n)


@external
@view
def p_oracle_down(n: int256) -> uint256:
    """
    @notice Lowest oracle price for the band to have liquidity when p = p_oracle
    @param n Band number (can be negative)
    @return Price at 1e18 base
    """
    return self._p_oracle_up(n + 1)


@internal
@view
def _get_y0(x: uint256, y: uint256, p_o: uint256, p_o_up: uint256) -> uint256:
    """
    @notice Calculate y0 for the invariant based on current liquidity in band.
            The value of y0 has a meaning of amount of collateral when band has no borrowed tokens
            but current price is equal to both oracle price and upper band price.
    @param x Amount of borrowed in band
    @param y Amount of collateral in band
    @param p_o External oracle price
    @param p_o_up Upper boundary of the band
    @return y0
    """
    assert p_o != 0
    # solve:
    # p_o * A * y0**2 - y0 * (p_oracle_up/p_o * (A-1) * x + p_o**2/p_oracle_up * A * y) - xy = 0
    b: uint256 = 0
    # p_o_up * unsafe_sub(A, 1) * x / p_o + A * p_o**2 / p_o_up * y / 10**18
    if x != 0:
        b = unsafe_div(p_o_up * Aminus1 * x, p_o)
    if y != 0:
        b += unsafe_div(A * p_o**2 // p_o_up * y, 10**18)
    if x > 0 and y > 0:
        D: uint256 = b**2 + unsafe_div((unsafe_mul(4, A) * p_o) * y, 10**18) * x
        return unsafe_div((b + self.sqrt_int(D)) * 10**18, unsafe_mul(unsafe_mul(2, A), p_o))
    else:
        return unsafe_div(b * 10**18, unsafe_mul(A, p_o))


@internal
@view
def _get_p(n: int256, x: uint256, y: uint256) -> uint256:
    """
    @notice Get current AMM price in band
    @param n Band number
    @param x Amount of borrowed in band
    @param y Amount of collateral in band
    @return Current price at 1e18 base
    """
    p_o_up: uint256 = self._p_oracle_up(n)
    p_o: uint256 = self._price_oracle_ro()[0]
    assert p_o_up != 0

    # Special cases
    if x == 0:
        if y == 0:  # x and y are 0
            # Return mid-band
            return unsafe_div((unsafe_div(unsafe_div(p_o**2, p_o_up) * p_o, p_o_up) * A), Aminus1)
        # if x == 0: # Lowest point of this band -> p_current_down
        return unsafe_div(unsafe_div(p_o**2, p_o_up) * p_o, p_o_up)
    if y == 0: # Highest point of this band -> p_current_up
        p_o_up = unsafe_div(p_o_up * Aminus1, A)  # now this is _actually_ p_o_down
        return unsafe_div(p_o**2 // p_o_up * p_o, p_o_up)

    y0: uint256 = self._get_y0(x, y, p_o, p_o_up)
    # ^ that call also checks that p_o != 0

    # (f(y0) + x) / (g(y0) + y)
    f: uint256 = unsafe_div(A * y0 * p_o, p_o_up) * p_o
    g: uint256 = unsafe_div(Aminus1 * y0 * p_o_up, p_o)
    return (f + x * 10**18) // (g + y)


@external
@view
@nonreentrant
def get_p() -> uint256:
    """
    @notice Get current AMM price in active_band
    @return Current price at 1e18 base
    """
    n: int256 = self.active_band
    return self._get_p(n, self.bands_x[n], self.bands_y[n])


@internal
@view
def _read_user_tick_numbers(user: address) -> int256[2]:
    """
    @notice Unpacks and reads user tick numbers
    @param user User address
    @return Lowest and highest band the user deposited into
    """
    ns: int256 = self.user_shares[user].ns
    n2: int256 = unsafe_div(ns, 2**128)
    n1: int256 = ns % 2**128
    if n1 >= 2**127:
        n1 = unsafe_sub(n1, 2**128)
        n2 = unsafe_add(n2, 1)
    return [n1, n2]


@external
@view
@nonreentrant
def read_user_tick_numbers(user: address) -> int256[2]:
    """
    @notice Unpacks and reads user tick numbers
    @param user User address
    @return Lowest and highest band the user deposited into
    """
    return self._read_user_tick_numbers(user)


@internal
@view
def _read_user_ticks(user: address, ns: int256[2]) -> DynArray[uint256, MAX_TICKS_UINT]:
    """
    @notice Unpacks and reads user ticks (shares) for all the ticks user deposited into
    @param user User address
    @param size Number of ticks the user deposited into
    @return Array of shares the user has
    """
    ticks: DynArray[uint256, MAX_TICKS_UINT] = []
    size: uint256 = convert(ns[1] - ns[0] + 1, uint256)
    for i: uint256 in range(MAX_TICKS_UINT // 2):
        if len(ticks) == size:
            break
        tick: uint256 = self.user_shares[user].ticks[i]
        ticks.append(tick & (2**128 - 1))
        if len(ticks) == size:
            break
        ticks.append(tick >> 128)
    return ticks


@external
@view
@nonreentrant
def can_skip_bands(n_end: int256) -> bool:
    """
    @notice Check that we have no liquidity between active_band and `n_end`
    """
    n: int256 = self.active_band
    for i: uint256 in range(MAX_SKIP_TICKS_UINT):
        if n_end > n:
            if self.bands_y[n] != 0:
                return False
            n = unsafe_add(n, 1)
        else:
            if self.bands_x[n] != 0:
                return False
            n = unsafe_sub(n, 1)
        if n == n_end:  # not including n_end
            break
    return True
    # Actually skipping bands:
    # * change self.active_band to the new n
    # * change self.p_base_mul
    # to do n2-n1 times (if n2 > n1):
    # out.base_mul = unsafe_div(out.base_mul * Aminus1, A)


@external
@view
@nonreentrant
def active_band_with_skip() -> int256:
    n0: int256 = self.active_band
    n: int256 = n0
    min_band: int256 = self.min_band
    for i: uint256 in range(MAX_SKIP_TICKS_UINT):
        if n < min_band:
            n = n0 - MAX_SKIP_TICKS
            break
        if self.bands_x[n] != 0:
            break
        n -= 1
    return n


@external
@view
@nonreentrant
def has_liquidity(user: address) -> bool:
    """
    @notice Check if `user` has any liquidity in the AMM
    """
    return self.user_shares[user].ticks[0] != 0


@internal
def save_user_shares(user: address, user_shares: DynArray[uint256, MAX_TICKS_UINT]):
    ptr: uint256 = 0
    for j: uint256 in range(MAX_TICKS_UINT // 2):
        if ptr >= len(user_shares):
            break
        tick: uint256 = user_shares[ptr]
        ptr = unsafe_add(ptr, 1)
        if len(user_shares) != ptr:
            tick = tick | (user_shares[ptr] << 128)
        ptr = unsafe_add(ptr, 1)
        self.user_shares[user].ticks[j] = tick


@external
@nonreentrant
def deposit_range(user: address, amount: uint256, n1: int256, n2: int256):
    """
    @notice Deposit for a user in a range of bands. Only admin contract (Controller) can do it
    @param user User address
    @param amount Amount of collateral to deposit
    @param n1 Lower band in the deposit range
    @param n2 Upper band in the deposit range
    """
    assert msg.sender == self.admin

    user_shares: DynArray[uint256, MAX_TICKS_UINT] = []
    collateral_shares: DynArray[uint256, MAX_TICKS_UINT] = []

    n0: int256 = self.active_band

    # We assume that n1,n2 area already sorted (and they are in Controller)
    assert n2 < 2**127
    assert n1 > -2**127

    n_bands: uint256 = unsafe_add(convert(unsafe_sub(n2, n1), uint256), 1)
    assert n_bands <= MAX_TICKS_UINT

    y_per_band: uint256 = unsafe_div(amount * COLLATERAL_PRECISION, n_bands)
    assert y_per_band > 100, "Amount too low"

    assert self.user_shares[user].ticks[0] == 0  # dev: User must have no liquidity
    self.user_shares[user].ns = unsafe_add(n1, unsafe_mul(n2, 2**128))

    lm: ILMGauge = self._liquidity_mining_callback

    # Autoskip bands if we can
    for i: uint256 in range(MAX_SKIP_TICKS_UINT + 1):
        if n1 > n0:
            if i != 0:
                self.active_band = n0
            break
        assert self.bands_x[n0] == 0 and i < MAX_SKIP_TICKS_UINT, "Deposit below current band"
        n0 -= 1

    for i: int256 in range(MAX_TICKS):
        band: int256 = unsafe_add(n1, i)
        if band > n2:
            break

        assert self.bands_x[band] == 0, "Band not empty"
        y: uint256 = y_per_band
        if i == 0:
            y = amount * COLLATERAL_PRECISION - y * unsafe_sub(n_bands, 1)

        total_y: uint256 = self.bands_y[band]

        # Total / user share
        s: uint256 = self.total_shares[band]
        ds: uint256 = unsafe_div((s + DEAD_SHARES) * y, total_y + 1)
        assert ds > 0, "Amount too low"
        user_shares.append(ds)
        s += ds
        assert s <= 2**128 - 1
        self.total_shares[band] = s

        total_y += y
        self.bands_y[band] = total_y

        if lm.address != empty(address):
            # If initial s == 0 - s becomes equal to y which is > 100 => nonzero
            collateral_shares.append(unsafe_div(total_y * 10**18, s))

    self.min_band = min(self.min_band, n1)
    self.max_band = max(self.max_band, n2)

    self.save_user_shares(user, user_shares)

    log IAMM.Deposit(provider=user, amount=amount, n1=n1, n2=n2)

    if lm.address != empty(address):
        success: bool = False
        res: Bytes[32] = empty(Bytes[32])
        success, res = raw_call(
            lm.address,
            abi_encode(
                n1, collateral_shares, n_bands,
                method_id=method_id("callback_collateral_shares(int256,uint256[],uint256)")
            ),
            max_outsize=32, revert_on_failure=False)
        success, res = raw_call(
            lm.address,
            abi_encode(
                user, n1, empty(DynArray[uint256, MAX_TICKS_UINT]), n_bands,
                method_id=method_id("callback_user_shares(address,int256,uint256[],uint256)")
            ),
            max_outsize=32, revert_on_failure=False)


@external
@nonreentrant
def withdraw(user: address, frac: uint256) -> uint256[2]:
    """
    @notice Withdraw liquidity for the user. Only admin contract can do it
    @param user User who owns liquidity
    @param frac Fraction to withdraw (1e18 being 100%)
    @return Amount of [borrowed, collateral] withdrawn
    """
    assert msg.sender == self.admin
    assert frac <= 10**18

    lm: ILMGauge = self._liquidity_mining_callback

    ns: int256[2] = self._read_user_tick_numbers(user)
    n: int256 = ns[0]
    old_user_shares: DynArray[uint256, MAX_TICKS_UINT] = self._read_user_ticks(user, ns)
    user_shares: DynArray[uint256, MAX_TICKS_UINT] = old_user_shares
    assert user_shares[0] > 0, "No deposits"

    total_x: uint256 = 0
    total_y: uint256 = 0
    min_band: int256 = self.min_band
    old_min_band: int256 = min_band
    old_max_band: int256 = self.max_band
    max_band: int256 = n - 1

    for i: uint256 in range(MAX_TICKS_UINT):
        x: uint256 = self.bands_x[n]
        y: uint256 = self.bands_y[n]
        ds: uint256 = unsafe_div(frac * user_shares[i], 10**18)
        user_shares[i] = unsafe_sub(user_shares[i], ds)  # Can ONLY zero out when frac == 10**18
        s: uint256 = self.total_shares[n]
        new_shares: uint256 = s - ds
        self.total_shares[n] = new_shares
        s += DEAD_SHARES  # after this s is guaranteed to be bigger than 0
        dx: uint256 = unsafe_div((x + 1) * ds, s)
        dy: uint256 = unsafe_div((y + 1) * ds, s)

        x -= dx
        y -= dy

        # If withdrawal is the last one - leave dust in the AMM
        if new_shares == 0:
            x = 0
            y = 0

        if n == min_band:
            if x == 0:
                if y == 0:
                    min_band += 1
        if x > 0 or y > 0:
            max_band = n
        self.bands_x[n] = x
        self.bands_y[n] = y
        total_x += dx
        total_y += dy

        if n == ns[1]:
            break
        else:
            n = unsafe_add(n, 1)

    # Empty the ticks
    if frac == 10**18:
        self.user_shares[user].ticks[0] = 0
    else:
        self.save_user_shares(user, user_shares)

    if old_min_band != min_band:
        self.min_band = min_band
    if old_max_band <= ns[1]:
        self.max_band = max_band

    total_x = unsafe_div(total_x, BORROWED_PRECISION)
    total_y = unsafe_div(total_y, COLLATERAL_PRECISION)
    log IAMM.Withdraw(provider=user, amount_borrowed=total_x, amount_collateral=total_y)

    if lm.address != empty(address):
        success: bool = False
        res: Bytes[32] = empty(Bytes[32])
        success, res = raw_call(
            lm.address,
            abi_encode(
                ns[0], empty(DynArray[uint256, MAX_TICKS_UINT]), len(old_user_shares),
                method_id=method_id("callback_collateral_shares(int256,uint256[],uint256)")
            ),
            max_outsize=32, revert_on_failure=False)
        success, res = raw_call(
            lm.address,
            abi_encode(
                user, ns[0], old_user_shares, len(old_user_shares),
                method_id=method_id("callback_user_shares(address,int256,uint256[],uint256)")
            ),
            max_outsize=32, revert_on_failure=False)

    return [total_x, total_y]


@internal
@view
def calc_swap_out(pump: bool, in_amount: uint256, p_o: uint256[2], in_precision: uint256, out_precision: uint256) -> IAMM.DetailedTrade:
    """
    @notice Calculate the amount which can be obtained as a result of exchange.
            If couldn't exchange all - will also update the amount which was actually used.
            Also returns other parameters related to state after swap.
            This function is core to the AMM functionality.
    @param pump Indicates whether the trade buys or sells collateral
    @param in_amount Amount of token going in
    @param p_o Current oracle price and ratio (p_o, dynamic_fee)
    @return Amounts spent and given out, initial and final bands of the AMM, new
            amounts of coins in bands in the AMM, as well as admin fee charged,
            all in one data structure
    """
    # pump = True: borrowable (USD) in, collateral (ETH) out; going up
    # pump = False: collateral (ETH) in, borrowable (USD) out; going down
    min_band: int256 = self.min_band
    max_band: int256 = self.max_band
    out: IAMM.DetailedTrade = empty(IAMM.DetailedTrade)
    out.n2 = self.active_band
    p_o_up: uint256 = self._p_oracle_up(out.n2)
    x: uint256 = self.bands_x[out.n2]
    y: uint256 = self.bands_y[out.n2]

    in_amount_left: uint256 = in_amount
    fee: uint256 = max(self.fee, p_o[1])
    j: uint256 = MAX_TICKS_UINT

    for i: uint256 in range(MAX_TICKS_UINT + MAX_SKIP_TICKS_UINT):
        y0: uint256 = 0
        f: uint256 = 0
        g: uint256 = 0
        Inv: uint256 = 0
        dynamic_fee: uint256 = fee

        if x > 0 or y > 0:
            if j == MAX_TICKS_UINT:
                out.n1 = out.n2
                j = 0
            y0 = self._get_y0(x, y, p_o[0], p_o_up)  # <- also checks p_o
            f = unsafe_div(A * y0 * p_o[0] // p_o_up * p_o[0], 10**18)
            g = unsafe_div(Aminus1 * y0 * p_o_up, p_o[0])
            Inv = (f + x) * (g + y)
            dynamic_fee = max(self.get_dynamic_fee(p_o[0], p_o_up), fee)

        antifee: uint256 = unsafe_div(
            (10**18)**2,
            unsafe_sub(10**18, min(dynamic_fee, 10**18 - 1))
        )

        if j != MAX_TICKS_UINT:
            # Initialize
            _tick: uint256 = y
            if pump:
                _tick = x
            out.ticks_in.append(_tick)

        # Need this to break if price is too far
        p_ratio: uint256 = unsafe_div(p_o_up * 10**18, p_o[0])

        if pump:
            if y != 0:
                if g != 0:
                    x_dest: uint256 = (unsafe_div(Inv, g) - f) - x
                    dx: uint256 = unsafe_div(x_dest * antifee, 10**18)
                    if dx >= in_amount_left:
                        # This is the last band
                        x_dest = unsafe_div(in_amount_left * 10**18, antifee)  # LESS than in_amount_left
                        out.last_tick_j = min(Inv // (f + (x + x_dest)) - g + 1, y)  # Should be always >= 0
                        x += in_amount_left  # x is precise after this
                        # Round down the output
                        out.out_amount += y - out.last_tick_j
                        out.ticks_in[j] = x
                        out.in_amount = in_amount
                        break

                    else:
                        # We go into the next band
                        dx = max(dx, 1)  # Prevents from leaving dust in the band
                        in_amount_left -= dx
                        out.ticks_in[j] = x + dx
                        out.in_amount += dx
                        out.out_amount += y

            if i != MAX_TICKS_UINT + MAX_SKIP_TICKS_UINT - 1:
                if out.n2 == max_band:
                    break
                if j == MAX_TICKS_UINT - 1:
                    break
                if p_ratio < unsafe_div(10**36, MAX_ORACLE_DN_POW):
                    # Don't allow to be away by more than ~50 ticks
                    break
                out.n2 += 1
                p_o_up = unsafe_div(p_o_up * Aminus1, A)
                x = 0
                y = self.bands_y[out.n2]

        else:  # dump
            if x != 0:
                if f != 0:
                    y_dest: uint256 = (unsafe_div(Inv, f) - g) - y
                    dy: uint256 = unsafe_div(y_dest * antifee, 10**18)
                    if dy >= in_amount_left:
                        # This is the last band
                        y_dest = unsafe_div(in_amount_left * 10**18, antifee)
                        out.last_tick_j = min(Inv // (g + (y + y_dest)) - f + 1, x)
                        y += in_amount_left
                        out.out_amount += x - out.last_tick_j
                        out.ticks_in[j] = y
                        out.in_amount = in_amount
                        break

                    else:
                        # We go into the next band
                        dy = max(dy, 1)  # Prevents from leaving dust in the band
                        in_amount_left -= dy
                        out.ticks_in[j] = y + dy
                        out.in_amount += dy
                        out.out_amount += x

            if i != MAX_TICKS_UINT + MAX_SKIP_TICKS_UINT - 1:
                if out.n2 == min_band:
                    break
                if j == MAX_TICKS_UINT - 1:
                    break
                if p_ratio > MAX_ORACLE_DN_POW:
                    # Don't allow to be away by more than ~50 ticks
                    break
                out.n2 -= 1
                p_o_up = unsafe_div(p_o_up * A, Aminus1)
                x = self.bands_x[out.n2]
                y = 0

        if j != MAX_TICKS_UINT:
            j = unsafe_add(j, 1)

    # Round up what goes in and down what goes out
    # ceil(in_amount_used/BORROWED_PRECISION) * BORROWED_PRECISION
    out.in_amount = unsafe_mul(unsafe_div(unsafe_add(out.in_amount, unsafe_sub(in_precision, 1)), in_precision), in_precision)
    out.out_amount = unsafe_mul(unsafe_div(out.out_amount, out_precision), out_precision)

    return out


@internal
@view
def _get_dxdy(i: uint256, j: uint256, amount: uint256, is_in: bool) -> IAMM.DetailedTrade:
    """
    @notice Method to use to calculate out amount and spent in amount
    @param i Input coin index
    @param j Output coin index
    @param amount Amount of input or output coin to swap
    @param is_in Whether IN our OUT amount is known
    @return DetailedTrade with all swap results
    """
    # i = 0: borrowable (USD) in, collateral (ETH) out; going up
    # i = 1: collateral (ETH) in, borrowable (USD) out; going down
    assert (i == 0 and j == 1) or (i == 1 and j == 0), "Wrong index"
    out: IAMM.DetailedTrade = empty(IAMM.DetailedTrade)
    if amount == 0:
        return out
    in_precision: uint256 = COLLATERAL_PRECISION
    out_precision: uint256 = BORROWED_PRECISION
    if i == 0:
        in_precision = BORROWED_PRECISION
        out_precision = COLLATERAL_PRECISION
    p_o: uint256[2] = self._price_oracle_ro()
    if is_in:
        out = self.calc_swap_out(i == 0, amount * in_precision, p_o, in_precision, out_precision)
    else:
        out = self.calc_swap_in(i == 0, amount * out_precision, p_o, in_precision, out_precision)
    out.in_amount = unsafe_div(out.in_amount, in_precision)
    out.out_amount = unsafe_div(out.out_amount, out_precision)
    return out


@external
@view
@nonreentrant
def get_dy(i: uint256, j: uint256, in_amount: uint256) -> uint256:
    """
    @notice Method to use to calculate out amount
    @param i Input coin index
    @param j Output coin index
    @param in_amount Amount of input coin to swap
    @return Amount of coin j to give out
    """
    return self._get_dxdy(i, j, in_amount, True).out_amount


@external
@view
@nonreentrant
def get_dxdy(i: uint256, j: uint256, in_amount: uint256) -> (uint256, uint256):
    """
    @notice Method to use to calculate out amount and spent in amount
    @param i Input coin index
    @param j Output coin index
    @param in_amount Amount of input coin to swap
    @return A tuple with in_amount used and out_amount returned
    """
    out: IAMM.DetailedTrade = self._get_dxdy(i, j, in_amount, True)
    return (out.in_amount, out.out_amount)


@internal
def _exchange(i: uint256, j: uint256, amount: uint256, minmax_amount: uint256, _for: address, use_in_amount: bool) -> uint256[2]:
    """
    @notice Exchanges two coins, callable by anyone
    @param i Input coin index
    @param j Output coin index
    @param amount Amount of input/output coin to swap
    @param minmax_amount Minimal/maximum amount to get as output/input
    @param _for Address to send coins to
    @param use_in_amount Whether input or output amount is specified
    @return Amount of coins given in and out
    """
    assert (i == 0 and j == 1) or (i == 1 and j == 0), "Wrong index"
    p_o: uint256[2] = self._price_oracle_w()  # Let's update the oracle even if we exchange 0
    if amount == 0:
        return [0, 0]

    lm: ILMGauge = self._liquidity_mining_callback
    collateral_shares: DynArray[uint256, MAX_TICKS_UINT] = []

    in_coin: IERC20 = BORROWED_TOKEN
    out_coin: IERC20 = COLLATERAL_TOKEN
    in_precision: uint256 = BORROWED_PRECISION
    out_precision: uint256 = COLLATERAL_PRECISION
    if i == 1:
        in_precision = out_precision
        in_coin = out_coin
        out_precision = BORROWED_PRECISION
        out_coin = BORROWED_TOKEN

    out: IAMM.DetailedTrade = empty(IAMM.DetailedTrade)
    if use_in_amount:
        out = self.calc_swap_out(i == 0, amount * in_precision, p_o, in_precision, out_precision)
    else:
        amount_to_swap: uint256 = max_value(uint256)
        if amount < amount_to_swap:
            amount_to_swap = amount * out_precision
        out = self.calc_swap_in(i == 0, amount_to_swap, p_o, in_precision, out_precision)
    in_amount_done: uint256 = unsafe_div(out.in_amount, in_precision)
    out_amount_done: uint256 = unsafe_div(out.out_amount, out_precision)
    if use_in_amount:
        assert out_amount_done >= minmax_amount, "Slippage"
    else:
        assert in_amount_done <= minmax_amount and (out_amount_done == amount or amount == max_value(uint256)), "Slippage"
    if out_amount_done == 0 or in_amount_done == 0:
        return [0, 0]

    n: int256 = min(out.n1, out.n2)
    n_start: int256 = n
    n_diff: int256 = abs(unsafe_sub(out.n2, out.n1))

    for k: int256 in range(MAX_TICKS):
        x: uint256 = 0
        y: uint256 = 0
        if i == 0:
            x = out.ticks_in[k]
            if n == out.n2:
                y = out.last_tick_j
        else:
            y = out.ticks_in[unsafe_sub(n_diff, k)]
            if n == out.n2:
                x = out.last_tick_j
        self.bands_x[n] = x
        self.bands_y[n] = y
        if lm.address != empty(address):
            s: uint256 = 0
            if y > 0:
                s = unsafe_div(y * 10**18, self.total_shares[n])
            collateral_shares.append(s)
        if k == n_diff:
            break
        n = unsafe_add(n, 1)

    self.active_band = out.n2

    log IAMM.TokenExchange(buyer=_for, sold_id=i, tokens_sold=in_amount_done, bought_id=j, tokens_bought=out_amount_done)

    if lm.address != empty(address):
        success: bool = False
        res: Bytes[32] = empty(Bytes[32])
        success, res = raw_call(
            lm.address,
            abi_encode(
                n_start, collateral_shares, len(collateral_shares),
                method_id=method_id("callback_collateral_shares(int256,uint256[],uint256)")
            ),
            max_outsize=32, revert_on_failure=False)

    tkn.transfer_from(in_coin, msg.sender, self, in_amount_done)
    tkn.transfer(out_coin, _for, out_amount_done)

    return [in_amount_done, out_amount_done]


@internal
@view
def calc_swap_in(pump: bool, out_amount: uint256, p_o: uint256[2], in_precision: uint256, out_precision: uint256) -> IAMM.DetailedTrade:
    """
    @notice Calculate the input amount required to receive the desired output amount.
            If couldn't exchange all - will also update the amount which was actually received.
            Also returns other parameters related to state after swap.
    @param pump Indicates whether the trade buys or sells collateral
    @param out_amount Desired amount of token going out
    @param p_o Current oracle price and antisandwich fee (p_o, dynamic_fee)
    @return Amounts required and given out, initial and final bands of the AMM, new
            amounts of coins in bands in the AMM, as well as admin fee charged,
            all in one data structure
    """
    # pump = True: borrowable (USD) in, collateral (ETH) out; going up
    # pump = False: collateral (ETH) in, borrowable (USD) out; going down
    min_band: int256 = self.min_band
    max_band: int256 = self.max_band
    out: IAMM.DetailedTrade = empty(IAMM.DetailedTrade)
    out.n2 = self.active_band
    p_o_up: uint256 = self._p_oracle_up(out.n2)
    x: uint256 = self.bands_x[out.n2]
    y: uint256 = self.bands_y[out.n2]

    out_amount_left: uint256 = out_amount
    fee: uint256 = max(self.fee, p_o[1])
    j: uint256 = MAX_TICKS_UINT

    for i: uint256 in range(MAX_TICKS_UINT + MAX_SKIP_TICKS_UINT):
        y0: uint256 = 0
        f: uint256 = 0
        g: uint256 = 0
        Inv: uint256 = 0
        dynamic_fee: uint256 = fee

        if x > 0 or y > 0:
            if j == MAX_TICKS_UINT:
                out.n1 = out.n2
                j = 0
            y0 = self._get_y0(x, y, p_o[0], p_o_up)  # <- also checks p_o
            f = unsafe_div(A * y0 * p_o[0] // p_o_up * p_o[0], 10**18)
            g = unsafe_div(Aminus1 * y0 * p_o_up, p_o[0])
            Inv = (f + x) * (g + y)
            dynamic_fee = max(self.get_dynamic_fee(p_o[0], p_o_up), fee)

        antifee: uint256 = unsafe_div(
            (10**18)**2,
            unsafe_sub(10**18, min(dynamic_fee, 10**18 - 1))
        )

        if j != MAX_TICKS_UINT:
            # Initialize
            _tick: uint256 = y
            if pump:
                _tick = x
            out.ticks_in.append(_tick)

        # Need this to break if price is too far
        p_ratio: uint256 = unsafe_div(p_o_up * 10**18, p_o[0])

        if pump:
            if y != 0:
                if g != 0:
                    if y >= out_amount_left:
                        # This is the last band
                        out.last_tick_j = unsafe_sub(y, out_amount_left)
                        x_dest: uint256 = Inv // (g + out.last_tick_j) - f - x
                        dx: uint256 = unsafe_div(x_dest * antifee, 10**18)  # MORE than x_dest
                        out.out_amount = out_amount  # We successfully found liquidity for all the out_amount
                        out.in_amount += dx
                        out.ticks_in[j] = x + dx
                        break

                    else:
                        # We go into the next band
                        x_dest: uint256 = (unsafe_div(Inv, g) - f) - x
                        dx: uint256 = max(unsafe_div(x_dest * antifee, 10**18), 1)
                        out_amount_left -= y
                        out.in_amount += dx
                        out.out_amount += y
                        out.ticks_in[j] = x + dx

            if i != MAX_TICKS_UINT + MAX_SKIP_TICKS_UINT - 1:
                if out.n2 == max_band:
                    break
                if j == MAX_TICKS_UINT - 1:
                    break
                if p_ratio < unsafe_div(10**36, MAX_ORACLE_DN_POW):
                    # Don't allow to be away by more than ~50 ticks
                    break
                out.n2 += 1
                p_o_up = unsafe_div(p_o_up * Aminus1, A)
                x = 0
                y = self.bands_y[out.n2]

        else:  # dump
            if x != 0:
                if f != 0:
                    if x >= out_amount_left:
                        # This is the last band
                        out.last_tick_j = unsafe_sub(x, out_amount_left)
                        y_dest: uint256 = Inv // (f + out.last_tick_j) - g - y
                        dy: uint256 = unsafe_div(y_dest * antifee, 10**18)  # MORE than y_dest
                        out.out_amount = out_amount
                        out.in_amount += dy
                        out.ticks_in[j] = y + dy
                        break

                    else:
                        # We go into the next band
                        y_dest: uint256 = (unsafe_div(Inv, f) - g) - y
                        dy: uint256 = max(unsafe_div(y_dest * antifee, 10**18), 1)
                        out_amount_left -= x
                        out.in_amount += dy
                        out.out_amount += x
                        out.ticks_in[j] = y + dy

            if i != MAX_TICKS_UINT + MAX_SKIP_TICKS_UINT - 1:
                if out.n2 == min_band:
                    break
                if j == MAX_TICKS_UINT - 1:
                    break
                if p_ratio > MAX_ORACLE_DN_POW:
                    # Don't allow to be away by more than ~50 ticks
                    break
                out.n2 -= 1
                p_o_up = unsafe_div(p_o_up * A, Aminus1)
                x = self.bands_x[out.n2]
                y = 0

        if j != MAX_TICKS_UINT:
            j = unsafe_add(j, 1)

    # Round up what goes in and down what goes out
    # ceil(in_amount_used/BORROWED_PRECISION) * BORROWED_PRECISION
    out.in_amount = unsafe_mul(unsafe_div(unsafe_add(out.in_amount, unsafe_sub(in_precision, 1)), in_precision), in_precision)
    out.out_amount = unsafe_mul(unsafe_div(out.out_amount, out_precision), out_precision)

    return out


@external
@view
@nonreentrant
def get_dx(i: uint256, j: uint256, out_amount: uint256) -> uint256:
    """
    @notice Method to use to calculate in amount required to receive the desired out_amount
    @param i Input coin index
    @param j Output coin index
    @param out_amount Desired amount of output coin to receive
    @return Amount of coin i to spend
    """
    # i = 0: borrowable (USD) in, collateral (ETH) out; going up
    # i = 1: collateral (ETH) in, borrowable (USD) out; going down
    trade: IAMM.DetailedTrade = self._get_dxdy(i, j, out_amount, False)
    assert trade.out_amount == out_amount
    return trade.in_amount


@external
@view
@nonreentrant
def get_dydx(i: uint256, j: uint256, out_amount: uint256) -> (uint256, uint256):
    """
    @notice Method to use to calculate in amount required and out amount received
    @param i Input coin index
    @param j Output coin index
    @param out_amount Desired amount of output coin to receive
    @return A tuple with out_amount received and in_amount returned
    """
    # i = 0: borrowable (USD) in, collateral (ETH) out; going up
    # i = 1: collateral (ETH) in, borrowable (USD) out; going down
    out: IAMM.DetailedTrade = self._get_dxdy(i, j, out_amount, False)
    return (out.out_amount, out.in_amount)


@external
@nonreentrant
def exchange(i: uint256, j: uint256, in_amount: uint256, min_amount: uint256, _for: address = msg.sender) -> uint256[2]:
    """
    @notice Exchanges two coins, callable by anyone
    @param i Input coin index
    @param j Output coin index
    @param in_amount Amount of input coin to swap
    @param min_amount Minimal amount to get as output
    @param _for Address to send coins to
    @return Amount of coins given in/out
    """
    return self._exchange(i, j, in_amount, min_amount, _for, True)


@external
@nonreentrant
def exchange_dy(i: uint256, j: uint256, out_amount: uint256, max_amount: uint256, _for: address = msg.sender) -> uint256[2]:
    """
    @notice Exchanges two coins, callable by anyone
    @param i Input coin index
    @param j Output coin index
    @param out_amount Desired amount of output coin to receive
    @param max_amount Maximum amount to spend (revert if more)
    @param _for Address to send coins to
    @return Amount of coins given in/out
    """
    return self._exchange(i, j, out_amount, max_amount, _for, False)


@internal
@view
def get_xy_up(user: address, use_y: bool) -> uint256:
    """
    @notice Measure the amount of y (collateral) in the band n if we adiabatically trade near p_oracle on the way up,
            or the amount of x (borrowed) if we trade adiabatically down
    @param user User the amount is calculated for
    @param use_y Calculate amount of collateral if True and of borrowed if False
    @return Amount of coins
    """
    ns: int256[2] = self._read_user_tick_numbers(user)
    ticks: DynArray[uint256, MAX_TICKS_UINT] = self._read_user_ticks(user, ns)
    if ticks[0] == 0:  # Even dynamic array will have 0th element set here
        return 0
    p_o: uint256 = self._price_oracle_ro()[0]
    assert p_o != 0

    n: int256 = ns[0] - 1
    n_active: int256 = self.active_band
    p_o_down: uint256 = self._p_oracle_up(ns[0])
    XY: uint256 = 0

    for i: uint256 in range(MAX_TICKS_UINT):
        n += 1
        if n > ns[1]:
            break
        x: uint256 = 0
        y: uint256 = 0
        if n >= n_active:
            y = self.bands_y[n]
        if n <= n_active:
            x = self.bands_x[n]
        # p_o_up: uint256 = self._p_oracle_up(n)
        p_o_up: uint256 = p_o_down
        # p_o_down = self._p_oracle_up(n + 1)
        p_o_down = unsafe_div(p_o_down * Aminus1, A)
        if x == 0:
            if y == 0:
                continue

        total_share: uint256 = self.total_shares[n]
        user_share: uint256 = ticks[i]
        if total_share == 0:
            continue
        if user_share == 0:
            continue
        total_share += DEAD_SHARES
        # Also ideally we'd want to add +1 to all quantities when calculating with shares
        # but we choose to save bytespace and slightly under-estimate the result of this call
        # which is also more conservative

        # Also this will revert if p_o_down is 0, and p_o_down is 0 if p_o_up is 0
        p_current_mid: uint256 = unsafe_div(p_o**2 // p_o_down * p_o, p_o_up)

        # if p_o > p_o_up - we "trade" everything to y and then convert to the result
        # if p_o < p_o_down - "trade" to x, then convert to result
        # otherwise we are in-band, so we do the more complex logic to trade
        # to p_o rather than to the edge of the band
        # trade to the edge of the band == getting to the band edge while p_o=const

        # Cases when special conversion is not needed (to save on computations)
        if x == 0 or y == 0:
            if p_o > p_o_up:  # p_o < p_current_down
                # all to y at constant p_o, then to target currency adiabatically
                y_equiv: uint256 = y
                if y == 0:
                    y_equiv = x * 10**18 // p_current_mid
                if use_y:
                    XY += unsafe_div(y_equiv * user_share, total_share)
                else:
                    XY += unsafe_div(unsafe_div(y_equiv * p_o_up, SQRT_BAND_RATIO) * user_share, total_share)
                continue

            elif p_o < p_o_down:  # p_o > p_current_up
                # all to x at constant p_o, then to target currency adiabatically
                x_equiv: uint256 = x
                if x == 0:
                    x_equiv = unsafe_div(y * p_current_mid, 10**18)
                if use_y:
                    XY += unsafe_div(unsafe_div(x_equiv * SQRT_BAND_RATIO, p_o_up) * user_share, total_share)
                else:
                    XY += unsafe_div(x_equiv * user_share, total_share)
                continue

        # If we are here - we need to "trade" to somewhere mid-band
        # So we need more heavy math

        y0: uint256 = self._get_y0(x, y, p_o, p_o_up)
        f: uint256 = unsafe_div(unsafe_div(A * y0 * p_o, p_o_up) * p_o, 10**18)
        g: uint256 = unsafe_div(Aminus1 * y0 * p_o_up, p_o)
        # (f + x)(g + y) = const = p_top * A**2 * y0**2 = I
        Inv: uint256 = (f + x) * (g + y)
        # p = (f + x) / (g + y) => p * (g + y)**2 = I or (f + x)**2 / p = I

        # First, "trade" in this band to p_oracle
        x_o: uint256 = 0
        y_o: uint256 = 0

        if p_o > p_o_up:  # p_o < p_current_down, all to y
            # x_o = 0
            y_o = crv_math.sub_or_zero(Inv // f, g)
            if use_y:
                XY += unsafe_div(y_o * user_share, total_share)
            else:
                XY += unsafe_div(unsafe_div(y_o * p_o_up, SQRT_BAND_RATIO) * user_share, total_share)

        elif p_o < p_o_down:  # p_o > p_current_up, all to x
            # y_o = 0
            x_o = crv_math.sub_or_zero(Inv // g, f)
            if use_y:
                XY += unsafe_div(unsafe_div(x_o * SQRT_BAND_RATIO, p_o_up) * user_share, total_share)
            else:
                XY += unsafe_div(x_o * user_share, total_share)

        else:
            # Equivalent from Chainsecurity (which also has less numerical errors):
            y_o = unsafe_div(A * y0 * unsafe_sub(p_o, p_o_down), p_o)
            # x_o = unsafe_div(A * y0 * p_o, p_o_up) * unsafe_sub(p_o_up, p_o)
            # Old math
            # y_o = crv_math.sub_or_zero(self.sqrt_int(unsafe_div(Inv * 10**18, p_o)), g)
            x_o = crv_math.sub_or_zero(Inv // (g + y_o), f)

            # Now adiabatic conversion from definitely in-band
            if use_y:
                XY += unsafe_div((y_o + x_o * 10**18 // self.sqrt_int(p_o_up * p_o)) * user_share, total_share)

            else:
                XY += unsafe_div((x_o + unsafe_div(y_o * self.sqrt_int(p_o_down * p_o), 10**18)) * user_share, total_share)

    if use_y:
        return unsafe_div(XY, COLLATERAL_PRECISION)
    else:
        return unsafe_div(XY, BORROWED_PRECISION)


@external
@view
@nonreentrant
def get_y_up(user: address) -> uint256:
    """
    @notice Measure the amount of y (collateral) in the band n if we adiabatically trade near p_oracle on the way up
    @param user User the amount is calculated for
    @return Amount of coins
    """
    return self.get_xy_up(user, True)


@external
@view
@nonreentrant
def get_x_down(user: address) -> uint256:
    """
    @notice Measure the amount of x (borrowed) if we trade adiabatically down
    @param user User the amount is calculated for
    @return Amount of coins
    """
    return self.get_xy_up(user, False)

@internal
@view
def _get_xy(user: address, is_sum: bool) -> DynArray[uint256, MAX_TICKS_UINT][2]:
    """
    @notice A low-gas function to measure amounts of borrowed and collateral tokens which user currently owns
    @param user User address
    @param is_sum Return sum or amounts by bands
    @return Amounts of (borrowed, collateral) in a tuple
    """
    xs: DynArray[uint256, MAX_TICKS_UINT] = []
    ys: DynArray[uint256, MAX_TICKS_UINT] = []
    if is_sum:
        xs.append(0)
        ys.append(0)
    ns: int256[2] = self._read_user_tick_numbers(user)
    ticks: DynArray[uint256, MAX_TICKS_UINT] = self._read_user_ticks(user, ns)
    if ticks[0] != 0:
        for i: uint256 in range(MAX_TICKS_UINT):
            total_shares: uint256 = self.total_shares[ns[0]] + DEAD_SHARES
            ds: uint256 = ticks[i]
            dx: uint256 = unsafe_div((self.bands_x[ns[0]] + 1) * ds, total_shares)
            dy: uint256 = unsafe_div((self.bands_y[ns[0]] + 1) * ds, total_shares)
            if is_sum:
                xs[0] += dx
                ys[0] += dy
            else:
                xs.append(unsafe_div(dx, BORROWED_PRECISION))
                ys.append(unsafe_div(dy, COLLATERAL_PRECISION))
            if ns[0] == ns[1]:
                break
            ns[0] = unsafe_add(ns[0], 1)

    if is_sum:
        xs[0] = unsafe_div(xs[0], BORROWED_PRECISION)
        ys[0] = unsafe_div(ys[0], COLLATERAL_PRECISION)

    return [xs, ys]

@external
@view
@nonreentrant
def get_sum_xy(user: address) -> uint256[2]:
    """
    @notice A low-gas function to measure amounts of borrowed and collateral tokens which user currently owns
    @param user User address
    @return Amounts of (borrowed, collateral) in a tuple
    """
    xy: DynArray[uint256, MAX_TICKS_UINT][2] = self._get_xy(user, True)
    return [xy[0][0], xy[1][0]]

@external
@view
@nonreentrant
def get_xy(user: address) -> DynArray[uint256, MAX_TICKS_UINT][2]:
    """
    @notice A low-gas function to measure amounts of borrowed and collateral tokens by bands which user currently owns
    @param user User address
    @return Amounts of (borrowed, collateral) by bands in a tuple
    """
    return self._get_xy(user, False)


@external
@view
@nonreentrant
def get_amount_for_price(p: uint256) -> (uint256, bool):
    """
    @notice Amount necessary to be exchanged to have the AMM at the final price `p`
    @return (amount, is_pump)
    """
    min_band: int256 = self.min_band
    max_band: int256 = self.max_band
    n: int256 = self.active_band
    p_o: uint256[2] = self._price_oracle_ro()
    p_o_up: uint256 = self._p_oracle_up(n)
    p_down: uint256 = unsafe_div(unsafe_div(p_o[0]**2, p_o_up) * p_o[0], p_o_up)  # p_current_down
    p_up: uint256 = unsafe_div(p_down * A2, Aminus12)  # p_crurrent_up
    amount: uint256 = 0
    y0: uint256 = 0
    f: uint256 = 0
    g: uint256 = 0
    Inv: uint256 = 0
    j: uint256 = MAX_TICKS_UINT
    pump: bool = True

    fee: uint256 = max(self.fee, p_o[1])

    for i: uint256 in range(MAX_TICKS_UINT + MAX_SKIP_TICKS_UINT):
        assert p_o_up > 0
        x: uint256 = self.bands_x[n]
        y: uint256 = self.bands_y[n]
        if i == 0:
            if p < self._get_p(n, x, y):
                pump = False
        dynamic_fee: uint256 = fee
        not_empty: bool = x > 0 or y > 0

        if not_empty:
            y0 = self._get_y0(x, y, p_o[0], p_o_up)
            f = unsafe_div(unsafe_div(A * y0 * p_o[0], p_o_up) * p_o[0], 10**18)
            g = unsafe_div(Aminus1 * y0 * p_o_up, p_o[0])
            Inv = (f + x) * (g + y)
            if j == MAX_TICKS_UINT:
                j = 0
            dynamic_fee = max(self.get_dynamic_fee(p_o[0], p_o_up), fee)

        antifee: uint256 = unsafe_div(
            (10**18)**2,
            unsafe_sub(10**18, min(dynamic_fee, 10**18 - 1))
        )

        if p <= p_up:
            if p >= p_down:
                if not_empty:
                    ynew: uint256 = crv_math.sub_or_zero(self.sqrt_int(Inv * 10**18 // p), g)
                    xnew: uint256 = crv_math.sub_or_zero(Inv // (g + ynew), f)
                    if pump:
                        amount += unsafe_div(crv_math.sub_or_zero(xnew, x) * antifee, 10**18)
                    else:
                        amount += unsafe_div(crv_math.sub_or_zero(ynew, y) * antifee, 10**18)
                break

        # Need this to break if price is too far
        p_ratio: uint256 = unsafe_div(p_o_up * 10**18, p_o[0])

        if pump:
            if not_empty:
                amount += unsafe_div(((Inv // g - f) - x) * antifee, 10**18)
            if n == max_band:
                break
            if j == MAX_TICKS_UINT - 1:
                break
            if p_ratio < unsafe_div(10**36, MAX_ORACLE_DN_POW):
                # Don't allow to be away by more than ~50 ticks
                break
            n += 1
            p_down = p_up
            p_up = unsafe_div(p_up * A2, Aminus12)
            p_o_up = unsafe_div(p_o_up * Aminus1, A)

        else:
            if not_empty:
                amount += unsafe_div(((Inv // f - g) - y) * antifee, 10**18)
            if n == min_band:
                break
            if j == MAX_TICKS_UINT - 1:
                break
            if p_ratio > MAX_ORACLE_DN_POW:
                # Don't allow to be away by more than ~50 ticks
                break
            n -= 1
            p_up = p_down
            p_down = unsafe_div(p_down * Aminus12, A2)
            p_o_up = unsafe_div(p_o_up * A, Aminus1)

        if j != MAX_TICKS_UINT:
            j = unsafe_add(j, 1)

    if amount == 0:
        return 0, pump

    # Precision and round up
    if pump:
        amount = unsafe_add(unsafe_div(unsafe_sub(amount, 1), BORROWED_PRECISION), 1)
    else:
        amount = unsafe_add(unsafe_div(unsafe_sub(amount, 1), COLLATERAL_PRECISION), 1)

    return amount, pump


@external
@nonreentrant
def set_rate(rate: uint256) -> uint256:
    """
    @notice Set interest rate. That affects the dependence of AMM base price over time
    @param rate New rate in units of int(fraction * 1e18) per second
    @return rate_mul multiplier (e.g. 1.0 + integral(rate, dt))
    """
    assert msg.sender == self.admin
    rate_mul: uint256 = self._rate_mul()
    self.rate_mul = rate_mul
    self.rate_time = block.timestamp
    self.rate = rate
    log IAMM.SetRate(rate=rate, rate_mul=rate_mul, time=block.timestamp)
    return rate_mul


@external
@nonreentrant
def set_fee(fee: uint256):
    """
    @notice Set AMM fee
    @param fee Fee where 1e18 == 100%
    """
    assert msg.sender == self.admin
    self.fee = fee
    log IAMM.SetFee(fee=fee)


# nonreentrant decorator is in Controller which is admin
@external
def set_callback(liquidity_mining_callback: ILMGauge):
    """
    @notice Set a gauge address with callbacks for liquidity mining for collateral
    @param liquidity_mining_callback Gauge address
    """
    assert msg.sender == self.admin
    self._liquidity_mining_callback = liquidity_mining_callback


@external
@nonreentrant
def set_price_oracle(_price_oracle: IPriceOracle):
    """
    @notice Set a new price oracle contract. Can only be called by admin (Controller)
    @param _price_oracle New price oracle contract
    """
    assert msg.sender == self.admin
    self._price_oracle = _price_oracle
    log IAMM.SetPriceOracle(price_oracle=_price_oracle)
