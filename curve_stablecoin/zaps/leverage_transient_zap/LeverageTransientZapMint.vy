# pragma version 0.4.3
# pragma optimize codesize

"""
@title LlamaLend V2 Mint Markets LeverageTransientZap
@author Curve.Finance
@license Copyright (c) Curve.Finance, 2020-2026 - all rights reserved
@notice Creates leverage on crvUSD V2 markets via whitelisted Aggregator Routers.
        Unlike LeverageZapMint, the zap itself is the entry point: the swap parameters
        are parked in transient storage for the duration of the controller call rather
        than being routed through the controller as `calldata`. Aggregator routes are
        therefore not capped by the controller's CALLDATA_MAX_SIZE. In exchange the
        user has to approve the zap on the controller, since the zap acts for them.
@custom:security security@curve.finance
@custom:kill Set is_approved_exchange False for all the exchanges.
"""

from curve_stablecoin.interfaces import IController
from curve_stablecoin.interfaces import IControllerFactory
from curve_stablecoin.interfaces import ILeverageTransientZap

implements: ILeverageTransientZap

from curve_stablecoin.zaps.leverage_transient_zap import LeverageTransientZapLend as core

initializes: core

# The callbacks need no factory lookup: they authenticate against the controller this
# zap is talking to, which its own entry points stashed.
exports: (
    core.version,
    core.max_borrowable,
    core.admin,
    core.set_exchange,
    core.is_approved_exchange,
    core.callback_deposit,
    core.callback_repay,
)

_MINT_FACTORY: immutable(IControllerFactory)


@deploy
def __init__(_factory: address, _exchanges: DynArray[address, core.MAX_INIT_EXCHANGES]):
    """
    @notice Contract constructor
    @param _factory Address of the factory the zap is associated with (used to look up controllers and the admin)
    @param _exchanges Initial list of exchanges (routers/pools) to add to the whitelist
    """
    _MINT_FACTORY = IControllerFactory(_factory)
    core.__init__(_factory, _exchanges)


@external
@view
def FACTORY() -> address:
    """
    @notice Factory the zap is associated with
    @return Address of the factory
    """
    return _MINT_FACTORY.address


@external
def create_loan(
        _controller_id: uint256,
        _collateral: uint256,
        _debt: uint256,
        _N: uint256,
        _min_recv: uint256,
        _exchange_address: address,
        _exchange_calldata: Bytes[core.EXCHANGE_CALLDATA_MAX_SIZE],
):
    """
    @notice Create a leveraged position
    @dev Requires `controller.approve(zap, True)` from the caller, since the zap
         creates the loan on their behalf
    @param _controller_id Index of the controller in the factory
    @param _collateral Amount of collateral token provided by the caller
    @param _debt Amount to borrow and swap for collateral
    @param _N Number of bands to deposit into
    @param _min_recv Minimum amount of collateral to receive from the exchange
    @param _exchange_address Address of the exchange (e. g. pool, router) to swap borrowed -> collateral
    @param _exchange_calldata Data for the exchange
    """
    core._create_loan(
        IController(staticcall _MINT_FACTORY.controllers(_controller_id)),
        _collateral,
        _debt,
        _N,
        _min_recv,
        _exchange_address,
        _exchange_calldata,
    )


@external
def borrow_more(
        _controller_id: uint256,
        _collateral: uint256,
        _debt: uint256,
        _min_recv: uint256,
        _exchange_address: address,
        _exchange_calldata: Bytes[core.EXCHANGE_CALLDATA_MAX_SIZE],
):
    """
    @notice Increase leverage on an existing position
    @dev Requires `controller.approve(zap, True)` from the caller
    @param _controller_id Index of the controller in the factory
    @param _collateral Amount of collateral token provided by the caller
    @param _debt Amount to borrow and swap for collateral
    @param _min_recv Minimum amount of collateral to receive from the exchange
    @param _exchange_address Address of the exchange (e. g. pool, router) to swap borrowed -> collateral
    @param _exchange_calldata Data for the exchange
    """
    core._borrow_more(
        IController(staticcall _MINT_FACTORY.controllers(_controller_id)),
        _collateral,
        _debt,
        _min_recv,
        _exchange_address,
        _exchange_calldata,
    )


@external
def repay(
        _controller_id: uint256,
        _wallet_d_debt: uint256,
        _min_recv: uint256,
        _exchange_address: address,
        _exchange_calldata: Bytes[core.EXCHANGE_CALLDATA_MAX_SIZE],
        _max_active_band: int256 = max_value(int256),
        _shrink: bool = False,
):
    """
    @notice Deleverage a position, selling its collateral for the borrowed token
    @dev Requires `controller.approve(zap, True)` from the caller. `_wallet_d_debt` is
         pulled from the caller up front, capped at the outstanding debt, so
         `max_value(uint256)` means "as much as needed". A full repay only consumes the
         part the swap did not cover; the rest is refunded.
    @param _controller_id Index of the controller in the factory
    @param _wallet_d_debt Amount of borrowed token the caller adds from their wallet
    @param _min_recv Minimum amount of borrowed token to receive from the exchange
    @param _exchange_address Address of the exchange (e. g. pool, router) to swap collateral -> borrowed
    @param _exchange_calldata Data for the exchange
    @param _max_active_band Don't allow active band to be higher than this (to prevent front-running the repay)
    @param _shrink Whether to shrink the soft-liquidated part of the position
    """
    core._repay(
        IController(staticcall _MINT_FACTORY.controllers(_controller_id)),
        _wallet_d_debt,
        _max_active_band,
        _min_recv,
        _exchange_address,
        _exchange_calldata,
        _shrink,
    )
