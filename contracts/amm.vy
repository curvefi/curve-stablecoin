# @version 0.3.1
from vyper.interfaces import ERC20

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


@internal
@view
def get_y0(n: int256) -> uint256:
    x: uint256 = self.bands_x[n]
    y: uint256 = self.bands_y[n]
    p_o: uint256 = self.price_oracle
    p_top: uint256 = self._p_oracle_band(n, False)

    # solve:
    # p_o * A * y0**2 - y0 * (p_top/p_o * (A-1) * x + p_o**2/p_top * A * y) - xy = 0
    b: uint256 = p_top * (A - 1) * x / p_o + A * p_o**2 / p_top * y / 10**18
    D: uint256 = b**2 + (4 * A) * p_o * y / 10**18 * x
    return (b + self.sqrt_int(D / 10**18)) * 10**18 / ((2 * A) * p_o)
