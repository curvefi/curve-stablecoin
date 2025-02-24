# @version 0.3.10

"""
@title LlamaLendPartialRepayZap
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
@notice Repays partially from position and increases health
"""

interface ERC20:
    def transfer(_to: address, _value: uint256) -> bool: nonpayable
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable
    def balanceOf(_for: address) -> uint256: view
    def allowance(_owner: address, _spender: address) -> uint256: view
    def approve(_spender: address, _value: uint256) -> bool: nonpayable
    def decimals() -> uint256: view


interface ControllerInterface:
    def BORROWED_TOKEN() -> address: view
    def COLLATERAL_TOKEN() -> address: view
    def n_loans() -> uint256: view
    def loans(n: uint256) -> address: view
    def user_state(user: address) -> uint256[4]: view
    def health(user: address) -> int256: view
    def tokens_to_liquidate(user: address, frac: uint256) -> uint256: view
    def approval(user: address, approved: address) -> bool: view
    def add_collateral(collateral: uint256, _for: address): nonpayable
    def repay(_d_debt: uint256, _for: address): nonpayable
    def liquidate_extended(user: address, min_x: uint256, frac: uint256, callbacker: address, callback_args: DynArray[uint256,5], callback_bytes: Bytes[10**4]): nonpayable


interface AMMInterface:
    def price_oracle() -> uint256: view
    def get_sum_xy(user: address) -> uint256[2]: view


struct Position:
    user: address
    x: uint256
    y: uint256
    health: int256
    dx: uint256  # collateral received from self-liquidate with defined FRAC
    dy: uint256  # borrowed needed to repay to self-liquidate with defined FRAC


CONTROLLER: public(immutable(ControllerInterface))
AMM: public(immutable(AMMInterface))
BORROWED: public(immutable(address))
COLLATERAL: public(immutable(address))

FRAC: public(immutable(uint256))  # fraction of position to repay
ORACLE_PRICE_SCALING_FACTOR: public(immutable(uint256))  # sell collateral at (ampl * oracle) price, 1 = 10 ** 18
HEALTH_THRESHOLD: public(immutable(uint256))  # dropping below this will "trigger" partial self-liquidate


@external
def __init__(
        _controller: address,
        _amm: address,
        _borrowed: address,
        _collateral: address,
        _frac: uint256,  # 4 * 10 ** 16 == 0.04
        _oracle_price_scaling_factor: uint256,  # 9 * 10 ** 17 == 0.9
        _health_threshold: uint256,  # 1 * 10 ** 16 == 1 or 1%
    ):
    CONTROLLER = ControllerInterface(_controller)
    AMM = AMMInterface(_amm)
    BORROWED = _borrowed
    COLLATERAL = _collateral

    FRAC = _frac
    ORACLE_PRICE_SCALING_FACTOR = _oracle_price_scaling_factor
    HEALTH_THRESHOLD = _health_threshold

    self._approve(COLLATERAL, _controller)
    self._approve(BORROWED, _controller)


@internal
def _transferFrom(token: address, _from: address, _to: address, amount: uint256):
    if amount > 0:
        assert ERC20(token).transferFrom(_from, _to, amount, default_return_value=True)


@internal
def _approve(coin: address, spender: address):
    if ERC20(coin).allowance(self, spender) == 0:
        assert ERC20(coin).approve(spender, max_value(uint256), default_return_value=True)


@internal
def transferFrom(token: ERC20, _from: address, _to: address, amount: uint256):
    if amount > 0:
        assert token.transferFrom(_from, _to, amount, default_return_value=True)


@internal
@view
def _collateral_from_liquidate(health: uint256, collateral: uint256) -> uint256:
    return ((10**18 + health / 2) * (10**18 - FRAC) / (10**18 + health) + FRAC) * FRAC * collateral / 10**36


@internal
@view
def _borrowed_from_collateral(dx: uint256) -> uint256:
    return dx * AMM.price_oracle() * ORACLE_PRICE_SCALING_FACTOR / 10 ** 36


@external
@view
def borrowed_from_collateral_needed(dx: uint256) -> uint256:
    return self._borrowed_from_collateral(dx)


@external
@view
def users_to_liquidate(_from: uint256 = 0, _limit: uint256 = 0) -> DynArray[Position, 1000]:
    """
    @notice Returns a dynamic array of users who can be "partially-liquidated".
            This method is designed for convenience of liquidation bots.
    @param _from Loan index to start iteration from
    @param _limit Number of loans to look over
    @return Dynamic array with detailed info about positions of users
    """
    n_loans: uint256 = CONTROLLER.n_loans()
    limit: uint256 = _limit
    if _limit == 0:
        limit = n_loans
    ix: uint256 = _from
    out: DynArray[Position, 1000] = []
    for i in range(10**6):
        if ix >= n_loans or i == limit:
            break
        user: address = CONTROLLER.loans(ix)
        health: int256 = CONTROLLER.health(user)
        if CONTROLLER.approval(user, self) and convert(health, uint256) < HEALTH_THRESHOLD:
            xy: uint256[2] = AMM.get_sum_xy(user)
            dx: uint256 = self._collateral_from_liquidate(convert(health, uint256), xy[1])
            dy: uint256 = CONTROLLER.tokens_to_liquidate(user, FRAC)
            out.append(Position({
                user: user,
                x: xy[0],
                y: xy[1],
                health: health,
                dx: dx,
                dy: dy
            }))

        ix += 1
    return out


@external
def repay_from_position(user: address, min_x: uint256):
    """
    @notice Repay from user's position to increase health
        Can be executed by anyone triggering selling of user's collateral at ORACLE_PRICE_SCALING_FACTOR * oracle price to arbitrageur
    @param user - user address
    @param min_x - minimal amount of borrowed withdrawn (to avoid being sandwiched)
    """
    assert CONTROLLER.approval(user, self), "User not approved this action"
    health: uint256 = convert(CONTROLLER.health(user), uint256)
    assert health < HEALTH_THRESHOLD, "not enough health to partially liquidate"

    xy: uint256[2] = AMM.get_sum_xy(user)
    collateral: uint256 = self._collateral_from_liquidate(health, xy[1])
    borrowed_from_sender: uint256 = self._borrowed_from_collateral(collateral)
    self.transferFrom(ERC20(BORROWED), msg.sender, self, borrowed_from_sender)

    CONTROLLER.liquidate_extended(user, min_x, FRAC, 0x0000000000000000000000000000000000000000, [], b"")

    collateral_received: uint256 = ERC20(COLLATERAL).balanceOf(self)
    assert ERC20(COLLATERAL).transfer(msg.sender, collateral_received)

    borrowed_amount: uint256 = ERC20(BORROWED).balanceOf(self)
    CONTROLLER.repay(borrowed_amount, user)
