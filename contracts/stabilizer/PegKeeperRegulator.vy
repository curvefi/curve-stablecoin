# @version 0.3.9
"""
@title Peg Keeper Regulator
@author Curve.Fi
@notice Regulations for Peg Keeper
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
    self.aggregator = _agg
    self.admin = _admin
    self.emergency_admin = _emergency_admin

    self.price_deviation = 5 * 10 ** (18 - 4) # 0.0005 = 0.05%


@external
@view
def stablecoin() -> address:
    return STABLECOIN


@internal
@pure
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
def _price_in_range(_p0: uint256, _p1: uint256) -> bool:
    """
    @notice Check that the price is in accepted range using absolute error
    @dev Needed for spam-attack protection
    """
    # |p1 - p0| <= deviation
    # -deviation <= p1 - p0 <= deviation
    # 0 < deviation + p1 - p0 <= 2 * deviation
    # can use unsafe
    deviation: uint256 = self.price_deviation
    return unsafe_sub(unsafe_add(deviation, _p0), _p1) < deviation << 1


@external
@view
def provide_allowed(_pk: address=msg.sender) -> bool:
    """
    @notice Allow PegKeeper to provide stablecoin into the pool
    @dev Checks
        1) current price in range of oracle in case of spam-attack
        2) current price location among other pools in case of contrary coin depeg
        3) stablecoin price is above 1
    """
    if self.is_killed in Killed.Provide:
        return False

    if self.aggregator.price() < 10 ** 18:
        return False

    pool: StableSwap = StableSwap(PegKeeper(_pk).pool())
    price: uint256 = max_value(uint256)  # Will fail if PegKeeper is not in self.price_pairs

    largest_price: uint256 = 0
    for pair in self.price_pairs:
        pair_price: uint256 = self._get_price_oracle(pair)
        if pair.pool.address == pool.address:
            price = pair_price
            if not self._price_in_range(price, self._get_price(pair)):
                return False
            continue
        elif largest_price < pair_price:
            largest_price = pair_price
    return largest_price >= unsafe_sub(price, 3 * 10 ** (18 - 4))


@external
@view
def withdraw_allowed(_pk: address=msg.sender) -> bool:
    """
    @notice Allow Peg Keeper to withdraw stablecoin from the pool
    @dev Checks
        1) current price in range of oracle in case of spam-attack
        2) stablecoin price is below 1
    """
    if self.is_killed in Killed.Withdraw:
        return False

    if self.aggregator.price() > 10 ** 18:
        return False

    pool: StableSwap = StableSwap(PegKeeper(_pk).pool())
    for pair in self.price_pairs:
        if pair.pool == pool:
            return self._price_in_range(self._get_price(pair), self._get_price_oracle(pair))
    return False  # dev: not found


@external
def add_price_pairs(_pools: DynArray[StableSwap, MAX_PAIRS]):
    assert msg.sender == self.admin

    for pool in _pools:
        price_pair: PricePair = empty(PricePair)
        price_pair.pool = pool
        coins: address[2] = [pool.coins(0), pool.coins(1)]
        if coins[0] == STABLECOIN:
            price_pair.is_inverse = True
        else:
            assert coins[1] == STABLECOIN
        self.price_pairs.append(price_pair)  # Should revert if too many pairs

        log AddPricePair(pool, price_pair.is_inverse)


@external
def remove_price_pairs(_pools: DynArray[StableSwap, MAX_PAIRS]):
    """
    @dev Most gas efficient will be sort pools reversely
    """
    assert msg.sender == self.admin

    price_pairs: DynArray[PricePair, MAX_PAIRS] = self.price_pairs
    max_n: uint256 = len(price_pairs) - 1
    for pool in _pools:
        i: uint256 = max_n
        for _ in range(MAX_PAIRS + 1):
            if price_pairs[i].pool == pool:
                break
            i -= 1  # dev: pool not found
        if i < max_n:
            price_pairs[i] = price_pairs[len(price_pairs) - 1]

        price_pairs.pop()
        log RemovePricePair(pool)
        if max_n > 0:
            max_n -= 1

    self.price_pairs = price_pairs


@external
def set_price_deviation(_deviation: uint256):
    """
    @notice Set acceptable deviation of current price from oracle's
    @param _deviation Deviation of price with base 10 ** 18 (1.0 = 10 ** 18)
    """
    assert msg.sender == self.admin
    assert _deviation <= 10 ** 20
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
