# pragma version 0.4.3
"""
@title Peg Keeper Regulator
@author Curve.Fi
@license MIT
@notice Regulations for Peg Keeper
@dev Diff from the previous version: optional per-keeper coin oracle blocks provide while the paired
    coin is depegged; provide_allowed() returns 0 instead of reverting when debt is above the limit.
@custom:kill admin or emergency_admin can pause provide and / or withdraw for all Peg Keepers
    via set_killed(). Keepers can be detached from this regulator by their owners.
@custom:version 1.1.0
"""


interface ERC20:
    def balanceOf(_owner: address) -> uint256: view


interface StableSwap:
    def get_p(_i: uint256 = 0) -> uint256: view
    def price_oracle(_i: uint256 = 0) -> uint256: view


interface PegKeeper:
    def pool() -> StableSwap: view
    def debt() -> uint256: view
    def IS_INVERSE() -> bool: view


interface Aggregator:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable


interface PriceOracle:
    def price() -> uint256: view


event AddPegKeeper:
    peg_keeper: PegKeeper
    pool: StableSwap
    is_inverse: bool


event RemovePegKeeper:
    peg_keeper: PegKeeper


event WorstPriceThreshold:
    threshold: uint256


event PriceDeviation:
    price_deviation: uint256


event DebtParameters:
    alpha: uint256
    beta: uint256


event SetAggregator:
    aggregator: address


event SetFeeReceiver:
    fee_receiver: address


event SetCoinOracle:
    peg_keeper: indexed(PegKeeper)
    oracle: address
    min_price: uint256


event SetKilled:
    is_killed: Killed
    by: address


event SetAdmin:
    admin: address


event SetEmergencyAdmin:
    admin: address


struct PegKeeperInfo:
    peg_keeper: PegKeeper
    pool: StableSwap
    is_inverse: bool
    include_index: bool


struct CoinOracle:
    oracle: PriceOracle  # empty(address) = no check
    min_price: uint256  # 1e18 = 1.0


flag Killed:
    Provide  # 1
    Withdraw  # 2

MAX_LEN: constant(uint256) = 8
ONE: constant(uint256) = 10**18

worst_price_threshold: public(uint256)
price_deviation: public(uint256)
alpha: public(uint256)  # Initial boundary
beta: public(uint256)  # Each PegKeeper's impact

STABLECOIN: immutable(ERC20)
aggregator: public(Aggregator)
peg_keepers: public(DynArray[PegKeeperInfo, MAX_LEN])
peg_keeper_i: HashMap[PegKeeper, uint256]  # 1 + index of peg keeper in a list
coin_oracle: public(HashMap[PegKeeper, CoinOracle])  # Optional depeg protection of the paired coin

fee_receiver: public(address)

is_killed: public(Killed)
admin: public(address)
emergency_admin: public(address)


@deploy
def __init__(
    _stablecoin: ERC20,
    _agg: Aggregator,
    _fee_receiver: address,
    _admin: address,
    _emergency_admin: address,
):
    STABLECOIN = _stablecoin
    self.aggregator = _agg
    self.fee_receiver = _fee_receiver
    self.admin = _admin
    self.emergency_admin = _emergency_admin
    log SetAdmin(admin=_admin)
    log SetEmergencyAdmin(admin=_emergency_admin)

    self.worst_price_threshold = 3 * 10**(18 - 4)  # 0.0003
    self.price_deviation = 5 * 10**(18 - 4)  # 0.0005 = 0.05%
    self.alpha = ONE // 2  # 1/2
    self.beta = ONE // 4  # 1/4
    log WorstPriceThreshold(threshold=self.worst_price_threshold)
    log PriceDeviation(price_deviation=self.price_deviation)
    log DebtParameters(alpha=self.alpha, beta=self.beta)


@external
@view
def stablecoin() -> ERC20:
    return STABLECOIN


@internal
@view
def _get_price(_info: PegKeeperInfo) -> uint256:
    """
    @return Price of the coin in STABLECOIN
    """
    price: uint256 = 0
    if _info.include_index:
        price = staticcall _info.pool.get_p(0)
    else:
        price = staticcall _info.pool.get_p()
    if _info.is_inverse:
        price = 10**36 // price
    return price


@internal
@view
def _get_price_oracle(_info: PegKeeperInfo) -> uint256:
    """
    @return Price of the coin in STABLECOIN
    """
    price: uint256 = 0
    if _info.include_index:
        price = staticcall _info.pool.price_oracle(0)
    else:
        price = staticcall _info.pool.price_oracle()
    if _info.is_inverse:
        price = 10**36 // price
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
    debt: uint256 = staticcall _peg_keeper.debt()
    return debt * ONE // (1 + debt + staticcall STABLECOIN.balanceOf(_peg_keeper.address))


@internal
@view
def _get_max_ratio(_debt_ratios: DynArray[uint256, MAX_LEN]) -> uint256:
    rsum: uint256 = 0
    for r: uint256 in _debt_ratios:
        rsum += isqrt(r * ONE)
    return (self.alpha + self.beta * rsum // ONE)**2 // ONE


@external
@view
def provide_allowed(_pk: address = msg.sender) -> uint256:
    """
    @notice Allow PegKeeper to provide stablecoin into the pool
    @dev Can return more amount than available
    @custom:dev Checks
        1) current price in range of oracle in case of spam-attack
        2) current price location among other pools in case of contrary coin depeg
        3) stablecoin price is above 1
        4) paired coin price from the optional coin oracle is above its min price
    @return Amount of stablecoin allowed to provide
    """
    if Killed.Provide in self.is_killed:
        return 0

    if staticcall self.aggregator.price() < ONE:
        return 0

    coin_oracle: CoinOracle = self.coin_oracle[PegKeeper(_pk)]
    if coin_oracle.oracle.address != empty(address):
        if staticcall coin_oracle.oracle.price() < coin_oracle.min_price:
            return 0
    price: uint256 = max_value(uint256)  # Will fail if PegKeeper is not in self.price_pairs
    largest_price: uint256 = 0
    debt_ratios: DynArray[uint256, MAX_LEN] = []
    for info: PegKeeperInfo in self.peg_keepers:
        price_oracle: uint256 = self._get_price_oracle(info)
        if info.peg_keeper.address == _pk:
            price = price_oracle
            if not self._price_in_range(price, self._get_price(info)):
                return 0
            continue
        elif largest_price < price_oracle:
            largest_price = price_oracle
        debt_ratios.append(self._get_ratio(info.peg_keeper))

    if largest_price < unsafe_sub(price, self.worst_price_threshold):
        return 0

    debt: uint256 = staticcall PegKeeper(_pk).debt()
    total: uint256 = debt + staticcall STABLECOIN.balanceOf(_pk)
    limit: uint256 = self._get_max_ratio(debt_ratios) * total // ONE
    if limit <= debt:
        return 0
    return limit - debt


@external
@view
def withdraw_allowed(_pk: address = msg.sender) -> uint256:
    """
    @notice Allow Peg Keeper to withdraw stablecoin from the pool
    @dev Can return more amount than available
    @custom:dev Checks
        1) current price in range of oracle in case of spam-attack
        2) stablecoin price is below 1
    @return Amount of stablecoin allowed to withdraw
    """
    if Killed.Withdraw in self.is_killed:
        return 0

    if staticcall self.aggregator.price() > ONE:
        return 0

    i: uint256 = self.peg_keeper_i[PegKeeper(_pk)]
    if i > 0:
        info: PegKeeperInfo = self.peg_keepers[i - 1]
        if self._price_in_range(self._get_price(info), self._get_price_oracle(info)):
            return max_value(uint256)
    return 0


@external
def add_peg_keepers(_peg_keepers: DynArray[PegKeeper, MAX_LEN]):
    assert msg.sender == self.admin

    i: uint256 = len(self.peg_keepers)
    for pk: PegKeeper in _peg_keepers:
        assert self.peg_keeper_i[pk] == empty(uint256)  # dev: duplicate
        pool: StableSwap = staticcall pk.pool()
        success: bool = raw_call(
            pool.address,
            abi_encode(convert(0, uint256), method_id=method_id("price_oracle(uint256)")),
            revert_on_failure=False,
        )
        info: PegKeeperInfo = PegKeeperInfo(
            peg_keeper=pk, pool=pool, is_inverse=staticcall pk.IS_INVERSE(), include_index=success
        )
        self.peg_keepers.append(info)  # dev: too many pairs
        i += 1
        self.peg_keeper_i[pk] = i

        log AddPegKeeper(peg_keeper=info.peg_keeper, pool=info.pool, is_inverse=info.is_inverse)


@external
def remove_peg_keepers(_peg_keepers: DynArray[PegKeeper, MAX_LEN]):
    """
    @dev Most gas efficient will be sort pools reversely
    """
    assert msg.sender == self.admin

    peg_keepers: DynArray[PegKeeperInfo, MAX_LEN] = self.peg_keepers
    for pk: PegKeeper in _peg_keepers:
        i: uint256 = self.peg_keeper_i[pk] - 1  # dev: pool not found
        max_n: uint256 = len(peg_keepers) - 1
        if i < max_n:
            peg_keepers[i] = peg_keepers[max_n]
            self.peg_keeper_i[peg_keepers[i].peg_keeper] = 1 + i

        peg_keepers.pop()
        self.peg_keeper_i[pk] = empty(uint256)
        self.coin_oracle[pk] = empty(CoinOracle)
        log RemovePegKeeper(peg_keeper=pk)

    self.peg_keepers = peg_keepers


@external
def set_coin_oracle(_pk: PegKeeper, _oracle: PriceOracle, _min_price: uint256):
    """
    @notice Block provide while the paired coin trades below _min_price. Empty oracle disables the check
    @param _pk Peg Keeper registered in this regulator
    @param _oracle Price oracle of the paired coin, 1e18 = 1.0
    @param _min_price Min price of the paired coin to allow provide, 1e18 = 1.0
    """
    assert msg.sender == self.admin
    assert self.peg_keeper_i[_pk] != 0  # dev: pool not found
    assert _min_price <= ONE  # dev: bad min price
    self.coin_oracle[_pk] = CoinOracle(oracle=_oracle, min_price=_min_price)
    log SetCoinOracle(peg_keeper=_pk, oracle=_oracle.address, min_price=_min_price)


@external
def set_worst_price_threshold(_threshold: uint256):
    """
    @notice Set threshold for the worst price that is still accepted
    @param _threshold Price threshold with base 10 ** 18 (1.0 = 10 ** 18)
    """
    assert msg.sender == self.admin
    assert _threshold <= 10**(18 - 2)  # 0.01
    self.worst_price_threshold = _threshold
    log WorstPriceThreshold(threshold=_threshold)


@external
def set_price_deviation(_deviation: uint256):
    """
    @notice Set acceptable deviation of current price from oracle's
    @param _deviation Deviation of price with base 10 ** 18 (1.0 = 10 ** 18)
    """
    assert msg.sender == self.admin
    assert _deviation <= 10**20
    self.price_deviation = _deviation
    log PriceDeviation(price_deviation=_deviation)


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
    log DebtParameters(alpha=_alpha, beta=_beta)


@external
def set_aggregator(_agg: Aggregator):
    """
    @notice Set new crvUSD price aggregator
    """
    assert msg.sender == self.admin
    self.aggregator = _agg
    log SetAggregator(aggregator=_agg.address)


@external
def set_fee_receiver(_fee_receiver: address):
    """
    @notice Set new PegKeeper's profit receiver
    """
    assert msg.sender == self.admin
    self.fee_receiver = _fee_receiver
    log SetFeeReceiver(fee_receiver=_fee_receiver)


@external
def set_killed(_is_killed: Killed):
    """
    @notice Pause/unpause Peg Keepers
    @dev 0 unpause, 1 provide, 2 withdraw, 3 everything
    """
    assert msg.sender in [self.admin, self.emergency_admin]
    self.is_killed = _is_killed
    log SetKilled(is_killed=_is_killed, by=msg.sender)


@external
def set_admin(_admin: address):
    # We are not doing commit / apply because the owner will be a voting DAO anyway
    # which has vote delays
    assert msg.sender == self.admin
    self.admin = _admin
    log SetAdmin(admin=_admin)


@external
def set_emergency_admin(_admin: address):
    assert msg.sender == self.admin
    self.emergency_admin = _admin
    log SetEmergencyAdmin(admin=_admin)
