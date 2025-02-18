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
    def add_collateral(collateral: uint256, _for: address): nonpayable
    def repay(_d_debt: uint256, _for: address): nonpayable
    def liquidate_extended(user: address, min_x: uint256, frac: uint256, callbacker: address, callback_args: DynArray[uint256,5], callback_bytes: Bytes[10**4]): nonpayable


ROUTER: public(immutable(address))
CONTROLLER: public(immutable(address))
BORROWED: public(immutable(address))
COLLATERAL: public(immutable(address))


@external
def __init__(_router: address, _controller: address, _borrowed: address, _collateral: address):
    ROUTER = _router
    CONTROLLER = _controller
    BORROWED = _borrowed
    COLLATERAL = _collateral

    self._approve(COLLATERAL, ROUTER)
    self._approve(COLLATERAL, CONTROLLER)
    self._approve(BORROWED, CONTROLLER)


@internal
def _transferFrom(token: address, _from: address, _to: address, amount: uint256):
    if amount > 0:
        assert ERC20(token).transferFrom(_from, _to, amount, default_return_value=True)


@internal
def _approve(coin: address, spender: address):
    if ERC20(coin).allowance(self, spender) == 0:
        assert ERC20(coin).approve(spender, max_value(uint256), default_return_value=True)

@external
@nonreentrant('lock')
def callback_liquidate(user: address, stablecoins: uint256, collateral: uint256, debt: uint256, callback_args: DynArray[uint256, 5], callback_bytes: Bytes[10**4]) -> uint256[2]:
    if callback_bytes != b"":
        raw_call(ROUTER, callback_bytes)  # sells collateral for borowed token

    return [ERC20(BORROWED).balanceOf(self), ERC20(COLLATERAL).balanceOf(self)]


@external
def repay_from_position(
    min_x: uint256, 
    callback_bytes: Bytes[10**4] = b"", 
    frac: uint256 = 3 * 10 ** 16
    ):
    """
    @notice Repay from position to increase health
    @param borrowed_token - borrowed token address
    @param collateral_token - collateral token address
    @param controller_address - address of the controller
    @param min_x - minimal amount of borrowed withdrawn (to avoid being sandwiched)
    @param frac - fraction of position to repay
    @param callback_bytes - parameters for router exchange
    """
    controller: ControllerInterface = ControllerInterface(CONTROLLER)
    user: address = msg.sender

    controller.liquidate_extended(user, min_x, frac, self, [], callback_bytes)

    borrowed_amount: uint256 = ERC20(BORROWED).balanceOf(self)
    controller.repay(borrowed_amount, user)

    additional_collateral: uint256 = ERC20(COLLATERAL).balanceOf(self)
    if additional_collateral > 0:
        ERC20(COLLATERAL).transfer(user, additional_collateral)
