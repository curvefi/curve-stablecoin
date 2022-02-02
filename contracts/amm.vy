# @version 0.3.1

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


@internal
@view
def p_oracle_up(n: int256) -> uint256:
    """
    Upper price of the band `n` when `p_oracle` == `p`
    """
    return self._p_oracle_band(n, False)


@internal
@view
def p_oracle_down(n: int256) -> uint256:
    """
    Lower price of the band `n` when `p_oracle` == `p`
    """
    return self._p_oracle_band(n, True)
