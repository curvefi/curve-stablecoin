# @version 0.3.1
from vyper.interfaces import ERC20

MAX_INT: constant(int256) = 57896044618658097711785492504343953926634992332820282019728792003956564819967  # 2**255 - 1
MAX_TICKS: constant(int256) = 50

struct UserTicks:
    ns: bytes32  # packs n1 and n2, each is int128
    ticks: uint256[MAX_TICKS/2]  # Share fractions packed 2 per slot

A: immutable(uint256)
COLLATERAL_TOKEN: immutable(address)  # y
BORROWED_TOKEN: immutable(address)    # x

fee: public(uint256)
rate: public(uint256)
base_price_0: uint256
base_price_time: uint256
active_band: public(int256)

price_oracle: public(uint256)
p_base_current: public(uint256)

bands_x: public(HashMap[int256, uint256])
bands_y: public(HashMap[int256, uint256])

total_shares: public(HashMap[int256, uint256])
user_shares: public(HashMap[address, UserTicks])


# Low-level math
@internal
@pure
def sqrt_int(x: uint256) -> uint256:
    """
    Originating from: https://github.com/vyperlang/vyper/issues/1266
    """

    if x == 0:
        return 0

    z: uint256 = (x + 10**18) / 2
    y: uint256 = x

    for i in range(256):
        if z == y:
            return y
        y = z
        z = (x * 10**18 / z + z) / 2

    raise "Did not converge"
# End of low-level math


@external
def __init__(_collateral_token: address, _borrowed_token: address,
             _A: uint256, _base_price: uint256,
             fee: uint256):
    A = _A
    self.base_price_0 = _base_price
    self.base_price_time = block.timestamp
    self.price_oracle = _base_price
    self.p_base_current = _base_price
    COLLATERAL_TOKEN = _collateral_token
    BORROWED_TOKEN = _borrowed_token
    self.fee = fee


@external
@view
def A() -> uint256:
    return A


@internal
@view
def _base_price() -> uint256:
    """
    Base price grows with time to account for interest rate (which is 0 by default)
    """
    return self.base_price_0 + self.rate * (block.timestamp - self.base_price_time) / 10**18


@external
@view
def base_price() -> uint256:
    return self._base_price()


@internal
@view
def _p_oracle_band(n: int256, is_down: bool) -> uint256:
    # k = (self.A - 1) / self.A  # equal to (p_up / p_down)
    # return self.p_base * k ** n
    n_active: int256 = self.active_band
    p_base: uint256 = self.p_base_current
    band_distance: int256 = abs(n - n_active)

    # k = (self.A - 1) / self.A  # equal to (p_up / p_down)
    # p_base = self.p_base * k ** (n_band + 1)
    for i in range(1000):
        if i == band_distance:
            break
        if n > n_active:
            p_base = p_base * (A - 1) / A
        else:
            p_base = p_base * A / (A - 1)
    if is_down:
        p_base = p_base * (A - 1) / A

    return p_base


@internal
@view
def _p_current_band(n: int256, is_up: bool) -> uint256:
    """
    Upper or lower price of the band `n` at current `p_oracle`
    """
    # k = (self.A - 1) / self.A  # equal to (p_up / p_down)
    # p_base = self.p_base * k ** (n_band + 1)
    p_base: uint256 = self._p_oracle_band(n, is_up)

    # return self.p_oracle**3 / p_base**2
    p_oracle: uint256 = self.price_oracle
    return p_oracle**2 / p_base * p_oracle / p_base


@external
@view
def p_current_up(n: int256) -> uint256:
    """
    Upper price of the band `n` at current `p_oracle`
    """
    return self._p_current_band(n, True)


@external
@view
def p_current_down(n: int256) -> uint256:
    """
    Lower price of the band `n` at current `p_oracle`
    """
    return self._p_current_band(n, False)


@external
@view
def p_oracle_up(n: int256) -> uint256:
    """
    Upper price of the band `n` when `p_oracle` == `p`
    """
    return self._p_oracle_band(n, False)


@external
@view
def p_oracle_down(n: int256) -> uint256:
    """
    Lower price of the band `n` when `p_oracle` == `p`
    """
    return self._p_oracle_band(n, True)


@external
def deposit_range(amount: uint256, n1: int256, n2: int256):
    n0: int256 = self.active_band
    assert n1 < n0 and n2 < n0, "Deposits should be below current band"
    assert ERC20(COLLATERAL_TOKEN).transferFrom(msg.sender, self, amount)

    y: uint256 = amount / (convert(abs(n2 - n1), uint256) + 1)

    band: int256 = min(n1, n2)
    finish: int256 = max(n1, n2)
    for i in range(1000):
        assert self.bands_x[band] == 0, "Band not empty"
        self.bands_y[band] += y
        band += 1
        if band > finish:
            break


@internal
@view
def _get_y0(x: uint256, y: uint256, p_o: uint256, p_o_up: uint256) -> uint256:
    # solve:
    # p_o * A * y0**2 - y0 * (p_oracle_up/p_o * (A-1) * x + p_o**2/p_oracle_up * A * y) - xy = 0
    b: uint256 = p_o_up * (A - 1) * x / p_o + A * p_o**2 / p_o_up * y / 10**18
    D: uint256 = b**2 + (4 * A) * p_o * y / 10**18 * x
    return (b + self.sqrt_int(D / 10**18)) * 10**18 / ((2 * A) * p_o)


@external
@view
def get_y0(n: int256) -> uint256:
    x: uint256 = self.bands_x[n]
    y: uint256 = self.bands_y[n]
    p_o: uint256 = self.price_oracle
    p_oracle_up: uint256 = 0
    if n == MAX_INT:
        p_oracle_up = self.p_base_current
    else:
        p_oracle_up = self._p_oracle_band(n, False)

    return self._get_y0(x, y, p_o, p_oracle_up)


@internal
@view
def _get_p(y0: uint256) -> uint256:
    n: int256 = self.active_band
    x: uint256 = self.bands_x[self.active_band]
    y: uint256 = self.bands_y[self.active_band]
    p_o_up: uint256 = self.p_base_current
    if x == 0 and y == 0:
        return p_o_up * (2 * A - 1) / (2 * A)
    p_o: uint256 = self.price_oracle

    _y0: uint256 = y0
    if _y0 == MAX_UINT256:
        _y0 = self._get_y0(x, y, p_o, p_o_up)

    # (f(y0) + x) / (g(y0) + y)
    f: uint256 = A * _y0 * p_o / p_o_up * p_o
    g: uint256 = (A - 1) * y0 * p_o_up / p_o
    return (f + x * 10**18) / (g + y)


@external
@view
def get_p() -> uint256:
    return self._get_p(MAX_UINT256)


@internal
def save_user_ticks(user: address, n1: int256, n2: int256, ticks: uint256[MAX_TICKS]):
    """
    Packs and saves user ticks
    """
    n1p: uint256 = convert(convert(convert(n1, int128), bytes32), uint256)
    n2p: uint256 = convert(convert(convert(n2, int128), bytes32), uint256)
    self.user_shares[user].ns = convert(bitwise_or(n1p, shift(n2p, 128)), bytes32)

    dist: uint256 = convert(abs(n1 - n2), uint256)
    ptr: uint256 = 0
    for i in range(MAX_TICKS / 2):
        if ptr > dist:
            break
        tick: uint256 = ticks[ptr]
        ptr += 1
        if dist != ptr:
            tick += shift(ticks[ptr], 128)
        ptr += 1
        self.user_shares[user].ticks[i] = tick


@internal
@view
def has_liquidity(user: address) -> bool:
    return self.user_shares[user].ns != empty(bytes32)


@internal
def empty_ticks(user: address):
    self.user_shares[user].ns = empty(bytes32)


@internal
@view
def read_user_tick_numbers(user: address) -> int256[2]:
    """
    Unpacks and reads user tick numbers
    """
    ns: uint256 = convert(self.user_shares[user].ns, uint256)
    n1: int256 = convert(convert(convert(bitwise_and(ns, 2**128 - 1), bytes32), int128), int256)
    n2: int256 = convert(convert(convert(shift(ns, -128), bytes32), int128), int256)
    return [n1, n2]


@internal
@view
def read_user_ticks(user: address, size: int256) -> uint256[MAX_TICKS]:
    """
    Unpacks and reads user ticks
    """
    ticks: uint256[MAX_TICKS] = empty(uint256[MAX_TICKS])
    ptr: int256 = 0
    for i in range(MAX_TICKS / 2):
        if ptr > size:
            break
        tick: uint256 = self.user_shares[user].ticks[i]
        ticks[ptr] = bitwise_and(tick, 2**128 - 1)
        ptr += 1
        if ptr != size:
            ticks[ptr] = shift(tick, -128)
        ptr += 1
    return ticks
