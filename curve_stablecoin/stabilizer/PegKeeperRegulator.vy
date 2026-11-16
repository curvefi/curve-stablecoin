# pragma version 0.4.3
"""
@title Peg Keeper Regulator
@author Curve.Fi
@license MIT
@notice Regulations for Peg Keeper
@dev Diff from the previous version: optional per-keeper coin oracle blocks provide while the paired
    coin is depegged; the worst price check and the alpha / beta debt limits are replaced by a rate
    limit: per its delta_window a keeper may provide up to the larger of debt_delta_share of the
    total debt of all keepers and ceiling_delta_share of its own debt ceiling, net of what it has
    provided in the window (rolling_delta()); provide_allowed() returns 0 instead of reverting when
    nothing is allowed; the spot-vs-EMA range check (price_deviation) is removed from both
    allowances.
@custom:kill admin or emergency_admin can pause provide and / or withdraw for all Peg Keepers
    via set_killed(); only admin can unpause. Keepers can be detached from this regulator by
    their owners.
@custom:version 1.1.0
"""


interface ERC20:
    def balanceOf(_owner: address) -> uint256: view


interface StableSwap:
    def price_oracle(_i: uint256 = 0) -> uint256: view


interface PegKeeper:
    def pool() -> StableSwap: view
    def debt() -> uint256: view
    def undrawn() -> uint256: view
    def rolling_delta() -> int256: view
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


event DeltaShares:
    debt_share: uint256
    ceiling_share: uint256


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

# Per delta_window a keeper may provide max(debt_delta_share * total debt, ceiling_delta_share * ceiling)
debt_delta_share: public(uint256)  # Share of the total debt of all keepers
ceiling_delta_share: public(uint256)  # Share of the keeper's own debt ceiling

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
    assert _stablecoin.address != empty(address)  # dev: bad stablecoin
    assert _agg.address != empty(address)  # dev: bad aggregator
    assert _fee_receiver != empty(address)  # dev: bad fee receiver
    assert _admin != empty(address)  # dev: bad admin
    assert _emergency_admin != empty(address)  # dev: bad emergency admin

    STABLECOIN = _stablecoin
    self.aggregator = _agg
    self.fee_receiver = _fee_receiver
    self.admin = _admin
    self.emergency_admin = _emergency_admin
    log SetAdmin(admin=_admin)
    log SetEmergencyAdmin(admin=_emergency_admin)

    self.debt_delta_share = ONE // 10  # 10%
    self.ceiling_delta_share = ONE // 20  # 5%
    log DeltaShares(debt_share=self.debt_delta_share, ceiling_share=self.ceiling_delta_share)


@external
@view
def stablecoin() -> ERC20:
    return STABLECOIN


# ----------------------------------- Allowance ----------------------------------


@internal
@view
def _total_debt() -> uint256:
    """
    @return Debt of all registered Peg Keepers
    """
    total: uint256 = 0
    for info: PegKeeperInfo in self.peg_keepers:
        total += staticcall info.peg_keeper.debt()
    return total


@internal
@view
def _delta_limit(_pk: PegKeeper) -> uint256:
    """
    @notice crvUSD the keeper may still provide in its delta window: the larger of debt_delta_share
        of the total debt and ceiling_delta_share of the keeper's debt ceiling (debt + undrawn),
        minus what it has provided net of withdrawn in the window
    """
    limit: int256 = convert(
        max(
            self.debt_delta_share * self._total_debt(),
            self.ceiling_delta_share * (staticcall _pk.debt() + staticcall _pk.undrawn()),
        ) // ONE,
        int256,
    )
    delta: int256 = staticcall _pk.rolling_delta()
    if delta >= limit:
        return 0
    return convert(limit - delta, uint256)


@external
@view
def provide_allowed(_pk: address = msg.sender) -> uint256:
    """
    @notice Allow PegKeeper to provide stablecoin into the pool
    @dev Can return more amount than available
    @custom:dev Checks
        1) stablecoin price is above 1
        2) paired coin price from the optional coin oracle is above its min price
        3) Peg Keeper is registered
        4) provided in the keeper's delta window is below its delta limit
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
    if self.peg_keeper_i[PegKeeper(_pk)] == 0:
        return 0
    return self._delta_limit(PegKeeper(_pk))


@external
@view
def withdraw_allowed(_pk: address = msg.sender) -> uint256:
    """
    @notice Allow Peg Keeper to withdraw stablecoin from the pool
    @dev Can return more amount than available
    @custom:dev Checks
        1) stablecoin price is below 1
        2) Peg Keeper is registered
    @return Amount of stablecoin allowed to withdraw
    """
    if Killed.Withdraw in self.is_killed:
        return 0

    if staticcall self.aggregator.price() > ONE:
        return 0

    if self.peg_keeper_i[PegKeeper(_pk)] == 0:
        return 0
    return max_value(uint256)


# ----------------------------------- Keepers ------------------------------------


@external
def add_peg_keepers(_peg_keepers: DynArray[PegKeeper, MAX_LEN]):
    """
    @notice Register Peg Keepers; pool and IS_INVERSE are read from each keeper
    @param _peg_keepers Peg Keepers to add
    """
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


# ------------------------------------ Admin -------------------------------------


@external
def set_delta_shares(_debt_share: uint256, _ceiling_share: uint256):
    """
    @notice Set the shares defining what a keeper may provide per its delta_window:
        the larger of _debt_share of the total debt and _ceiling_share of its own debt ceiling
    @param _debt_share Share of the total debt of all keepers, base 10 ** 18
    @param _ceiling_share Share of the keeper's debt ceiling, base 10 ** 18
    """
    assert msg.sender == self.admin
    assert _debt_share <= ONE  # dev: bad share
    assert _ceiling_share <= ONE  # dev: bad share

    self.debt_delta_share = _debt_share
    self.ceiling_delta_share = _ceiling_share
    log DeltaShares(debt_share=_debt_share, ceiling_share=_ceiling_share)


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
    @dev 0 unpause, 1 provide, 2 withdraw, 3 everything. Emergency admin can only pause
    """
    if msg.sender != self.admin:
        assert msg.sender == self.emergency_admin  # dev: only admin or emergency admin
        assert self.is_killed & _is_killed == self.is_killed  # dev: emergency admin can only pause
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
