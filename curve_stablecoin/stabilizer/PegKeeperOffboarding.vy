# pragma version 0.3.10
"""
@title Peg Keeper Offboarding
@author Curve.Fi
@notice Allows PK to withdraw stablecoin without taking new debt
@license MIT
@custom:version 0.0.1
"""

version: public(constant(String[8])) = "0.0.1"


interface ERC20:
    def balanceOf(_owner: address) -> uint256: view

interface StableSwap:
    def get_p(i: uint256=0) -> uint256: view
    def price_oracle(i: uint256=0) -> uint256: view

interface PegKeeper:
    def pool() -> StableSwap: view
    def debt() -> uint256: view
    def IS_INVERSE() -> bool: view

event AddPegKeeper:
    peg_keeper: PegKeeper
    pool: StableSwap
    is_inverse: bool

event RemovePegKeeper:
    peg_keeper: PegKeeper

event SetFeeReceiver:
    fee_receiver: address

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

enum Killed:
    Provide  # 1
    Withdraw  # 2

MAX_LEN: constant(uint256) = 32

peg_keepers: public(DynArray[PegKeeperInfo, MAX_LEN])  # PKs registered for offboarding
peg_keeper_i: HashMap[PegKeeper,  uint256]  # 1 + index of peg keeper in a list

fee_receiver: public(address)

is_killed: public(Killed)
admin: public(address)
emergency_admin: public(address)


@external
def __init__(_fee_receiver: address, _admin: address, _emergency_admin: address):
    self.fee_receiver = _fee_receiver
    self.admin = _admin
    self.emergency_admin = _emergency_admin
    log SetFeeReceiver(_fee_receiver)
    log SetAdmin(_admin)
    log SetEmergencyAdmin(_emergency_admin)


@external
@view
def provide_allowed(_pk: address=msg.sender) -> uint256:
    """
    @notice Do not allow PegKeeper to provide more
    @return Amount of stablecoin allowed to provide
    """
    return 0



@external
@view
def withdraw_allowed(_pk: address=msg.sender) -> uint256:
    """
    @notice Allow Peg Keeper to withdraw stablecoin from the pool
    @return Amount of stablecoin allowed to withdraw
    """
    if self.is_killed in Killed.Withdraw:
        return 0
    return max_value(uint256)


@external
def add_peg_keepers(_peg_keepers: DynArray[PegKeeper, MAX_LEN]):
    assert msg.sender == self.admin

    i: uint256 = len(self.peg_keepers)
    for pk in _peg_keepers:
        assert self.peg_keeper_i[pk] == empty(uint256)  # dev: duplicate
        pool: StableSwap = pk.pool()
        success: bool = raw_call(
            pool.address, _abi_encode(convert(0, uint256), method_id=method_id("price_oracle(uint256)")),
            revert_on_failure=False
        )
        info: PegKeeperInfo = PegKeeperInfo({
            peg_keeper: pk,
            pool: pool,
            is_inverse: pk.IS_INVERSE(),
            include_index: success,
        })
        self.peg_keepers.append(info)  # dev: too many pairs
        i += 1
        self.peg_keeper_i[pk] = i

        log AddPegKeeper(info.peg_keeper, info.pool, info.is_inverse)


@external
def remove_peg_keepers(_peg_keepers: DynArray[PegKeeper, MAX_LEN]):
    """
    @dev Most gas efficient will be sort pools reversely
    """
    assert msg.sender == self.admin

    peg_keepers: DynArray[PegKeeperInfo, MAX_LEN] = self.peg_keepers
    for pk in _peg_keepers:
        i: uint256 = self.peg_keeper_i[pk] - 1  # dev: pool not found
        max_n: uint256 = len(peg_keepers) - 1
        if i < max_n:
            peg_keepers[i] = peg_keepers[max_n]
            self.peg_keeper_i[peg_keepers[i].peg_keeper] = 1 + i

        peg_keepers.pop()
        self.peg_keeper_i[pk] = empty(uint256)
        log RemovePegKeeper(pk)

    self.peg_keepers = peg_keepers


@external
def set_fee_receiver(_fee_receiver: address):
    """
    @notice Set new PegKeeper's profit receiver
    """
    assert msg.sender == self.admin
    self.fee_receiver = _fee_receiver
    log SetFeeReceiver(_fee_receiver)


@external
def set_killed(_is_killed: Killed):
    """
    @notice Pause/unpause Peg Keepers
    @dev 0 unpause, 1 provide, 2 withdraw, 3 everything
    """
    assert msg.sender in [self.admin, self.emergency_admin]
    self.is_killed = _is_killed
    log SetKilled(_is_killed, msg.sender)


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
    log SetEmergencyAdmin(_admin)
