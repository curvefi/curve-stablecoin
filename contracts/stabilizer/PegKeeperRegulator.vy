# @version 0.3.9
"""
@title Peg Keeper Regulator
@author Curve.Fi
@notice Regulations for Peg Keeper
@license MIT
"""

interface ERC20:
    def balanceOf(_owner: address) -> uint256: view

interface StableSwap:
    def get_p() -> uint256: view
    def price_oracle() -> uint256: view

interface PegKeeper:
    def pool() -> StableSwap: view
    def debt() -> uint256: view
    def IS_INVERSE() -> bool: view

interface Aggregator:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable

event AddPegKeeper:
    peg_keeper: PegKeeper
    pool: StableSwap
    is_inverse: bool

event RemovePegKeeper:
    peg_keeper: PegKeeper

event SetAdmin:
    admin: address

struct PegKeeperInfo:
    peg_keeper: PegKeeper
    pool: StableSwap
    is_inverse: bool

enum Killed:
    Provide  # 1
    Withdraw  # 2

MAX_LEN: constant(uint256) = 8
ONE: constant(uint256) = 10 ** 18

LAST_PRICE_THRESHOLD: constant(uint256) = 3 * 10 ** (18 - 4)  # 0.0003
price_deviation: public(uint256)
alpha: public(uint256)  # Initial boundary
beta: public(uint256)  # Each PegKeeper's impact

STABLECOIN: immutable(ERC20)
aggregator: public(Aggregator)
peg_keepers: public(DynArray[PegKeeperInfo, MAX_LEN])

is_killed: public(Killed)
admin: public(address)
emergency_admin: public(address)


@external
def __init__(_stablecoin: ERC20, _agg: Aggregator, _admin: address, _emergency_admin: address):
    STABLECOIN = _stablecoin
    self.aggregator = _agg
    self.admin = _admin
    self.emergency_admin = _emergency_admin

    self.price_deviation = 5 * 10 ** (18 - 4) # 0.0005 = 0.05%
    self.alpha = ONE / 2 # 1/2
    self.beta = ONE / 4  # 1/4


@external
@view
def stablecoin() -> ERC20:
    return STABLECOIN


@internal
@pure
def _get_price(_info: PegKeeperInfo) -> uint256:
    """
    @return Price of the coin in STABLECOIN
    """
    price: uint256 = _info.pool.get_p()
    if _info.is_inverse:
        price = 10 ** 36 / price
    return price


@internal
@pure
def _get_price_oracle(_info: PegKeeperInfo) -> uint256:
    """
    @return Price of the coin in STABLECOIN
    """
    price: uint256 = _info.pool.price_oracle()
    if _info.is_inverse:
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


@internal
@view
def _get_ratio(_peg_keeper: PegKeeper) -> uint256:
    """
    @return debt ratio limited up to 1
    """
    debt: uint256 = _peg_keeper.debt()
    return debt * ONE / (1 + debt + STABLECOIN.balanceOf(_peg_keeper.address))


@internal
@view
def _get_max_ratio(_debt_ratios: DynArray[uint256, MAX_LEN]) -> uint256:
    rsum: uint256 = 0
    for r in _debt_ratios:
        rsum += isqrt(r * ONE)
    return (self.alpha + self.beta * rsum / ONE) ** 2 / ONE


@external
@view
def provide_allowed(_pk: address=msg.sender) -> uint256:
    """
    @notice Allow PegKeeper to provide stablecoin into the pool
    @dev Can return more amount than available
    @dev Checks
        1) current price in range of oracle in case of spam-attack
        2) current price location among other pools in case of contrary coin depeg
        3) stablecoin price is above 1
    @return Amount of stablecoin allowed to provide
    """
    if self.is_killed in Killed.Provide:
        return 0

    if self.aggregator.price() < ONE:
        return 0

    price: uint256 = max_value(uint256)  # Will fail if PegKeeper is not in self.price_pairs
    largest_price: uint256 = 0
    debt_ratios: DynArray[uint256, MAX_LEN] = []
    for info in self.peg_keepers:
        price_oracle: uint256 = self._get_price_oracle(info)
        if info.peg_keeper.address == _pk:
            price = price_oracle
            if not self._price_in_range(price, self._get_price(info)):
                return 0
            continue
        elif largest_price < price_oracle:
            largest_price = price_oracle
        debt_ratios.append(self._get_ratio(info.peg_keeper))

    if largest_price < unsafe_sub(price, LAST_PRICE_THRESHOLD):
        return 0

    debt: uint256 = PegKeeper(_pk).debt()
    total: uint256 = debt + STABLECOIN.balanceOf(_pk)
    return self._get_max_ratio(debt_ratios) * total / ONE - debt



@external
@view
def withdraw_allowed(_pk: address=msg.sender) -> uint256:
    """
    @notice Allow Peg Keeper to withdraw stablecoin from the pool
    @dev Can return more amount than available
    @dev Checks
        1) current price in range of oracle in case of spam-attack
        2) stablecoin price is below 1
    @return Amount of stablecoin allowed to withdraw
    """
    if self.is_killed in Killed.Withdraw:
        return 0

    if self.aggregator.price() > ONE:
        return 0

    for info in self.peg_keepers:
        if info.peg_keeper.address == _pk:
            if self._price_in_range(self._get_price(info), self._get_price_oracle(info)):
                return max_value(uint256)
            else:
                return 0
    return 0  # dev: not found


@external
def add_peg_keepers(_peg_keepers: DynArray[PegKeeper, MAX_LEN]):
    assert msg.sender == self.admin

    for pk in _peg_keepers:
        info: PegKeeperInfo = PegKeeperInfo({
            peg_keeper: pk,
            pool: pk.pool(),
            is_inverse: pk.IS_INVERSE(),
        })
        self.peg_keepers.append(info)  # Should revert if too many pairs

        log AddPegKeeper(info.peg_keeper, info.pool, info.is_inverse)


@external
def remove_peg_keepers(_peg_keepers: DynArray[PegKeeper, MAX_LEN]):
    """
    @dev Most gas efficient will be sort pools reversely
    """
    assert msg.sender == self.admin

    peg_keepers: DynArray[PegKeeperInfo, MAX_LEN] = self.peg_keepers
    max_n: uint256 = len(peg_keepers) - 1
    for pk in _peg_keepers:
        i: uint256 = max_n
        for _ in range(MAX_LEN + 1):
            if peg_keepers[i].peg_keeper == pk:
                break
            i -= 1  # dev: pool not found
        if i < max_n:
            peg_keepers[i] = peg_keepers[len(peg_keepers) - 1]

        peg_keepers.pop()
        log RemovePegKeeper(pk)
        if max_n > 0:
            max_n -= 1

    self.peg_keepers = peg_keepers


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
def set_debt_parameters(_alpha: uint256, _beta: uint256):
    """
    @notice Set parameters for calculation of debt limits
    @dev 10 ** 18 precision
    """
    assert msg.sender == self.admin
    assert _alpha <= ONE
    assert _beta <= ONE

    self.alpha = _alpha
    self.beta = _beta


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
