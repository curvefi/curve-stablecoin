# @version 0.3.9
"""
@title Peg Keeper Controller
@author Curve.Fi
@notice Conditions for Peg Keeper
@dev Checks that current price is in range of oracle and in top-3 of all kept pools.
@license MIT
"""

interface StableSwap:
    def get_p() -> uint256: view
    def price_oracle() -> uint256: view
    def coins(i: uint256) -> address: view

interface PegKeeper:
    def pool() -> address: view

interface Aggregator:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable

struct PricePair:
    pool: StableSwap
    is_inverse: bool


event AddPricePair:
    pool: StableSwap
    is_inverse: bool

event RemovePricePair:
    pool: StableSwap

event SetAdmin:
    admin: address


enum Killed:
    Provide  # 1
    Withdraw  # 2

MAX_PAIRS: constant(uint256) = 8

price_deviation: public(uint256)

STABLECOIN: immutable(address)
aggregator: public(Aggregator)
price_pairs: public(DynArray[PricePair, MAX_PAIRS])

is_killed: public(Killed)
admin: public(address)
emergency_admin: public(address)


@external
def __init__(_stablecoin: address, _agg: Aggregator, _admin: address, _emergency_admin: address):
    STABLECOIN = _stablecoin
    self.aggregator = _agg  # TODO should we use?
    self.admin = _admin
    self.emergency_admin = _emergency_admin

    self.price_deviation = 10 ** 18 / 10  # 10%


@external
@view
def stablecoin() -> address:
    return STABLECOIN


@internal
@view
def _get_price(_pair: PricePair) -> uint256:
    """
    @return Price of the coin in STABLECOIN
    """
    price: uint256 = _pair.pool.get_p()
    if _pair.is_inverse:
        price = 10 ** 36 / price
    return price


@internal
@pure
def _get_price_oracle(_pair: PricePair) -> uint256:
    """
    @return Price of the coin in STABLECOIN
    """
    price: uint256 = _pair.pool.price_oracle()
    if _pair.is_inverse:
        price = 10 ** 36 / price
    return price


@internal
@view
def _price_in_range(_p: uint256, _price_oracle: uint256) -> bool:
    """
    @notice Check that the price is in accepted range using absolute percentage error
    @dev Needed for spam-attack protection
    """
    if _p <= _price_oracle:
        return unsafe_sub(_price_oracle, _p) < _price_oracle * self.price_deviation / 10 ** 18
    return unsafe_sub(_p, _price_oracle) < _price_oracle * self.price_deviation / 10 ** 18


@external
@view
def provide_allowed(_pk: address=msg.sender) -> bool:
    """
    @notice Allow PegKeeper to provide stablecoin into the pool
    @dev Checks
        1) current price in range of oracle in case of spam-attack
        2) current price location among other pools in case of contrary coin depeg
    """
    if self.is_killed in Killed.Provide:
        return False

    pool: StableSwap = StableSwap(PegKeeper(_pk).pool())
    price: uint256 = 0  # Will fail if PegKeeper is not in self.price_pairs

    smallest_price: uint256 = max_value(uint256)
    for pair in self.price_pairs:
        pair_price: uint256 = self._get_price(pair)
        if pair.pool.address == pool.address:
            price = pair_price
            if not self._price_in_range(price, self._get_price_oracle(pair)):
                return False
            continue

        if smallest_price > pair_price:
            smallest_price = pair_price
    return smallest_price < price


@external
@view
def withdraw_allowed(_pk: address=msg.sender) -> bool:
    """
    @notice Allow Peg Keeper to withdraw stablecoin from the pool
    @dev Checks
        1) current price in range of oracle in case of spam-attack
        2) current price location among other pools in case of contrary coin depeg
    """
    if self.is_killed in Killed.Withdraw:
        return False

    pool: StableSwap = StableSwap(PegKeeper(_pk).pool())
    price: uint256 = max_value(uint256)  # Will fail if PegKeeper is not in self.price_pairs

    largest_price: uint256 = min_value(uint256)
    for pair in self.price_pairs:
        pair_price: uint256 = self._get_price(pair)
        if pair.pool == pool:
            price = pair_price
            if not self._price_in_range(price, self._get_price_oracle(pair)):
                return False
            continue

        if largest_price < pair_price:
            largest_price = pair_price
    return largest_price > price


@external
def add_price_pair(_pool: StableSwap):
    assert msg.sender == self.admin

    price_pair: PricePair = empty(PricePair)
    price_pair.pool = _pool
    coins: address[2] = [_pool.coins(0), _pool.coins(1)]
    if coins[0] == STABLECOIN:
        price_pair.is_inverse = True
    else:
        assert coins[1] == STABLECOIN
    self.price_pairs.append(price_pair)  # Should revert if too many pairs

    log AddPricePair(_pool, price_pair.is_inverse)


@external
def remove_price_pair(_pool: StableSwap):
    assert msg.sender == self.admin

    i: uint256 = 0
    for price_pair in self.price_pairs:
        if self.price_pairs[i].pool == _pool:
            break
        i += 1

    n_max: uint256 = len(self.price_pairs) - 1
    if i < n_max:
        self.price_pairs[i] = self.price_pairs[n_max]
    elif i > n_max:
        raise "Pool not found"

    self.price_pairs.pop()
    log RemovePricePair(_pool)


@external
def set_price_deviation(_deviation: uint256):
    """
    @notice Set acceptable deviation of current price from oracle's
    @param _deviation Deviation of price with base 10 ** 18 (100% = 10 ** 18)
    """
    assert msg.sender == self.admin
    self.price_deviation = _deviation


@external
def set_killed(_is_killed: Killed):
    """
    @notice Pause/unpause Peg Keepers
    @dev 0 unpause, 1 provide, 2 withdraw, 3 everything
    """
    assert msg.sender in [self.admin, self.emergency_admin]
    self.is_killed = _is_killed


@external
def set_admin(_admin: address):
    # We are not doing commit / apply because the owner will be a voting DAO anyway
    # which has vote delays
    assert msg.sender == self.admin
    self.admin = _admin
    log SetAdmin(_admin)


@external
def set_emergency_admin(_admin: address):
    assert msg.sender == self.admin
    self.emergency_admin = _admin
