# pragma version 0.4.3
# pragma nonreentrancy on
"""
@title Llamalend Controller View Contract
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2025 - all rights reserved
@notice This contract never requires any direct interaction as the
    main controller contract forwards all relevant calls.
@custom:security security@curve.fi
@custom:kill Stateless contract doesn't need to be killed.
"""

from curve_std.interfaces import IERC20
from curve_stablecoin.interfaces import IController
from curve_stablecoin.interfaces import ILendController
from curve_stablecoin.interfaces import IAMM
from curve_stablecoin.interfaces import IControllerView
from curve_std import math as crv_math

implements: IControllerView

from curve_stablecoin import ControllerView as core

initializes: core
exports: (
    core.min_collateral,
    core.user_state,
    core.user_prices,
    core.users_to_liquidate,
    core.create_loan_health_preview,
    core.add_collateral_health_preview,
    core.remove_collateral_health_preview,
    core.borrow_more_health_preview,
    core.repay_health_preview,
    core.liquidate_health_preview,
    core.calculate_debt_n1,
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
    ll_core: ILendController = ILendController(
        core.CONTROLLER.address
    )
    return staticcall ll_core.borrow_cap()


@internal
@view
def _available_balance() -> uint256:
    ll_core: ILendController = ILendController(
        core.CONTROLLER.address
    )
    return staticcall ll_core.available_balance()


@internal
@view
def _get_cap() -> uint256:
    """
    @notice Cannot borrow beyond the amount of coins Controller has or beyond borrow_cap
    """
    total_debt: uint256 = self._total_debt()
    cap: uint256 = crv_math.sub_or_zero(self._borrow_cap(), total_debt)
    return min(self._available_balance(), cap)


@external
@view
def max_borrowable(
    _collateral: uint256,
    _N: uint256,
    _current_debt: uint256 = 0,
    _user: address = empty(address),
) -> uint256:
    """
    @notice Natspec for this function is available in its controller contract
    """
    return core._max_borrowable(_collateral, _N, self._get_cap() + _current_debt , _user)


@external
@view
def tokens_to_shrink(_user: address, _d_collateral: uint256 = 0) -> uint256:
    """
    @notice Natspec for this function is available in its controller contract
    """
    return core._tokens_to_shrink(_user, self._get_cap(), _d_collateral)
