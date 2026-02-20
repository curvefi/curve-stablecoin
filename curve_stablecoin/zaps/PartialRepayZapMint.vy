# pragma version 0.4.3

"""
@title LlamaLendPartialRepayZap
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2025 - all rights reserved
@notice Partially repays a position (self-liquidation) when health is low,
        using controller callback to forward assets directly to the caller.
"""

from curve_stablecoin.interfaces import IController
from curve_stablecoin.interfaces import IControllerFactory

from curve_stablecoin.interfaces import IPartialRepayZap as IZap

implements: IZap

from curve_stablecoin.zaps import PartialRepayZapLending as core

initializes: core

exports: (
    core.FRAC,
    core.HEALTH_THRESHOLD
)

_MINT_FACTORY: immutable(IControllerFactory)

@view
@external
def FACTORY() -> address:
    return _MINT_FACTORY.address


@deploy
def __init__(
        _factory: address,
        _frac: uint256,                       # e.g. 5e16 == 5%
        _health_threshold: int256,            # e.g. 1e16 == 1%
    ):
    _MINT_FACTORY = IControllerFactory(_factory)
    core.__init__(_factory, _frac, _health_threshold)


@internal
@view
def _get_controller(_c_idx: uint256) -> IController:
    return IController(staticcall _MINT_FACTORY.controllers(_c_idx))


@internal
@view
def _check_controller(_controller: address, _c_idx: uint256):
    assert _controller == self._get_controller(_c_idx).address


@external
@view
def users_to_liquidate(
    _c_idx: uint256,
    _from: uint256 = 0,
    _limit: uint256 = 0,
) -> DynArray[IZap.Position, 1000]:
    """
    @notice Returns users eligible for partial self-liquidation through this zap.
    @param _c_idx Index of the market in the factory
    @param _from Loan index to start iteration from
    @param _limit Number of loans to inspect (0 = all)
    @return Dynamic array with position info and zap-specific estimates
    """
    return core._users_to_liquidate(
        self._get_controller(_c_idx),
        _from,
        _limit,
    )


@external
def liquidate_partial(
    _c_idx: uint256,
    _user: address,
    _min_x: uint256,
    _exchange_contract: address = empty(address),
    _exchange_calldata: Bytes[core.CALLDATA_MAX_SIZE - 32 * 5] = b"",
):
    """
    @notice Trigger partial self-liquidation of `user` using FRAC.
            Caller supplies borrowed tokens; receives withdrawn collateral.
    @param _c_idx Index of the market in the factory
    @param _user Address of the position owner (must have approved this zap in controller)
    @param _min_x Minimal x withdrawn from AMM to guard against MEV
    @param _exchange_contract Address of the exchange contract (aggregator, router, etc.)
    @param _exchange_calldata Calldata for the exchange contract
    """
    core._liquidate_partial(
        self._get_controller(_c_idx),
        _c_idx,
        _user,
        _min_x,
        _exchange_contract,
        _exchange_calldata,
    )


@external
def callback_liquidate(
    _user: address,
    _borrowed: uint256,
    _collateral: uint256,
    _debt: uint256,
    _calldata: Bytes[core.CALLDATA_MAX_SIZE],
) -> uint256[2]:
    """
    @notice Controller callback invoked during liquidate.
    @dev Provides borrowed tokens back to controller to cover shortfall and
         forwards collateral to the liquidator via controller.transferFrom.
    """
    c_idx: uint256 = 0
    borrowed_from_sender: uint256 = 0
    exchange_contract: address = empty(address)
    exchange_calldata: Bytes[core.CALLDATA_MAX_SIZE - 32 * 5] = empty(Bytes[core.CALLDATA_MAX_SIZE - 32 * 5])

    c_idx, borrowed_from_sender, exchange_contract, exchange_calldata = abi_decode(_calldata, (uint256, uint256, address, Bytes[core.CALLDATA_MAX_SIZE - 32 * 5]))

    self._check_controller(msg.sender, c_idx)

    raw_call(exchange_contract, exchange_calldata)

    return [borrowed_from_sender, 0]
