# pragma version 0.4.3
# pragma nonreentrancy on
"""
@title Llamalend Controller View Contract
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2025 - all rights reserved
@notice This contract never requires any direct interaction as the
    main controller contract forwards all relevant calls.
"""

from contracts.interfaces import IERC20
from contracts.interfaces import IController
from contracts.interfaces import ILlamalendController
from contracts.interfaces import IAMM
from contracts.interfaces import IControllerView

implements: IControllerView

from contracts import ControllerView as core

initializes: core
exports: (
    core.min_collateral,
    core.user_state,
    core.user_prices,
    core.users_to_liquidate,
    core.health_calculator,
)


@deploy
def __init__(
    _controller: IController,
    _sqrt_band_ratio: uint256,
    _logn_a_ratio: int256,
    _amm: IAMM,
    _A: uint256,
    _collateral_token: IERC20,
    _collateral_precision: uint256,
    _borrowed_token: IERC20,
    _borrowed_precision: uint256
):
    core.__init__(
        _controller,
        _sqrt_band_ratio,
        _logn_a_ratio,
        _amm,
        _A,
        _collateral_token,
        _collateral_precision,
        _borrowed_token,
        _borrowed_precision
    )


@internal
@view
def _total_debt() -> uint256:
    return staticcall core.CONTROLLER.total_debt()


@internal
@view
def _borrow_cap() -> uint256:
    ll_core: ILlamalendController = ILlamalendController(
        core.CONTROLLER.address
    )
    return staticcall ll_core.borrow_cap()


@internal
@view
def _available_balance() -> uint256:
    ll_core: ILlamalendController = ILlamalendController(
        core.CONTROLLER.address
    )
    return staticcall ll_core.available_balance()


@external
@view
def max_borrowable(
    collateral: uint256,
    N: uint256,
    current_debt: uint256 = 0,
    user: address = empty(address),
) -> uint256:
    """
    @notice Natspec for this function is available in its controller contract
    """
    # Cannot borrow beyond the amount of coins Controller has or beyond borrow_cap
    total_debt: uint256 = self._total_debt()
    cap: uint256 = unsafe_sub(max(self._borrow_cap(), total_debt), total_debt)
    cap = min(self._available_balance(), cap) + current_debt

    return core._max_borrowable(collateral, N, cap, user)
