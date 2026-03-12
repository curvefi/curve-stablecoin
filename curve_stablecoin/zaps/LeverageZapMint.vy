# pragma version 0.4.3
# pragma optimize codesize

"""
@title LlamaLendLeverageZapMint
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2026 - all rights reserved
@notice Creates leverage on crvUSD markets via any Aggregator Router. Does calculations for leverage.
"""

from curve_stablecoin.interfaces import IControllerFactory
from curve_stablecoin.interfaces import ILeverageZap

implements: ILeverageZap

from curve_stablecoin.zaps import LeverageZapLending as core

initializes: core

exports: core.max_borrowable

_MINT_FACTORY: immutable(IControllerFactory)


@deploy
def __init__(_factory: address):
    _MINT_FACTORY = IControllerFactory(_factory)
    core.__init__(_factory)


@external
@view
def FACTORY() -> address:
    return _MINT_FACTORY.address


@external
@nonreentrant
def callback_deposit(
        _user: address,
        _borrowed: uint256,
        _user_collateral: uint256,
        _d_debt: uint256,
        _calldata: Bytes[core.CALLDATA_MAX_SIZE],
) -> uint256[2]:
    """
    @notice Callback method which should be called by controller to create leveraged position
    @param _user Address of the user
    @param _borrowed Always 0
    @param _user_collateral The amount of collateral token provided by user
    @param _d_debt The amount to be borrowed (in addition to what has already been borrowed)
    @param _calldata controller_id + user_borrowed + min_recv + exchange_address + exchange_calldata
                    - controller_id is needed to check that msg.sender is the one of our controllers
                    - user_borrowed - the amount of borrowed token provided by user (needs to be exchanged for collateral)
                    - min_recv - the minimum amount to receive from exchange of (user_borrowed + d_debt) for collateral tokens
                    - exchange_address - the address of the exchange (e. g. pool, router) to swap borrowed -> collateral
                    - exchange_calldata - the data for the exchange (e. g. pool, router)
    return [0, user_collateral_from_borrowed + leverage_collateral]
    """
    controller_id: uint256 = 0
    user_borrowed: uint256 = 0
    min_recv: uint256 = 0
    exchange_address: address = empty(address)
    exchange_calldata: Bytes[core.CALLDATA_MAX_SIZE - 6 * 32] = empty(Bytes[core.CALLDATA_MAX_SIZE - 6 * 32])
    controller_id, user_borrowed, min_recv, exchange_address, exchange_calldata = abi_decode(
        _calldata, (uint256, uint256, uint256, address, Bytes[core.CALLDATA_MAX_SIZE - 6 * 32])
    )

    controller: address = staticcall _MINT_FACTORY.controllers(controller_id)
    assert msg.sender == controller, "wrong controller"

    return core._callback_deposit(controller, _user, _user_collateral, _d_debt, user_borrowed, min_recv, exchange_address, exchange_calldata)


@external
@nonreentrant
def callback_repay(
        _user: address,
        _borrowed: uint256,
        _collateral: uint256,
        _debt: uint256,
        _calldata: Bytes[core.CALLDATA_MAX_SIZE],
) -> uint256[2]:
    """
    @notice Callback method which should be called by controller to create leveraged position
    @param _user Address of the user
    @param _borrowed The value from user_state
    @param _collateral The value from user_state
    @param _debt The value from user_state
    @param _calldata controller_id + user_collateral + user_borrowed + min_recv + exchange_address + exchange_calldata
                    - controller_id is needed to check that msg.sender is the one of our controllers
                    - user_collateral - the amount of collateral token provided by user (needs to be exchanged for borrowed)
                    - user_borrowed - the amount of borrowed token to repay from user's wallet
                    - min_recv - the minimum amount to receive from exchange of (user_collateral + state_collateral) for borrowed tokens
                    - exchange_address - the address of the exchange (e. g. pool, router) to swap collateral -> borrowed
                    - exchange_calldata - the data for the exchange (e. g. pool, router)
    return [user_borrowed + borrowed_from_collateral, remaining_collateral]
    """
    controller_id: uint256 = 0
    user_collateral: uint256 = 0
    user_borrowed: uint256 = 0
    min_recv: uint256 = 0
    exchange_address: address = empty(address)
    exchange_calldata: Bytes[core.CALLDATA_MAX_SIZE - 7 * 32] = empty(Bytes[core.CALLDATA_MAX_SIZE - 7 * 32])
    controller_id, user_collateral, user_borrowed, min_recv, exchange_address, exchange_calldata = abi_decode(
        _calldata, (uint256, uint256, uint256, uint256, address, Bytes[core.CALLDATA_MAX_SIZE - 7 * 32])
    )

    controller: address = staticcall _MINT_FACTORY.controllers(controller_id)
    assert msg.sender == controller, "wrong controller"

    return core._callback_repay(controller, _user, user_collateral, user_borrowed, min_recv, exchange_address, exchange_calldata)
