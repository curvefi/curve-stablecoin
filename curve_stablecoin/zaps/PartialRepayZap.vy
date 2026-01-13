# pragma version 0.4.3
# pragma nonreentrancy on

"""
@title LlamaLendPartialRepayZap
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2025 - all rights reserved
@notice Partially repays a position (self-liquidation) when health is low.
        Liquidator provides borrowed tokens, receives withdrawn collateral.
"""

from curve_std.interfaces import IERC20
from curve_stablecoin.interfaces import IAMM
from curve_stablecoin.interfaces import IController
from curve_stablecoin import controller as ctrl
from curve_stablecoin import ControllerView as view
from curve_std import token as tkn
from curve_stablecoin.interfaces import IPartialRepayZap as IZap

from curve_stablecoin import constants as c

implements: IZap

# https://github.com/vyperlang/vyper/issues/4723
WAD: constant(uint256) = c.WAD

FRAC: public(immutable(uint256))                         # fraction of position to repay (1e18 = 100%)
HEALTH_THRESHOLD: public(immutable(int256))              # trigger threshold on controller.health(user, false)


@deploy
def __init__(
        _frac: uint256,                       # e.g. 5e16 == 5%
        _health_threshold: int256,            # e.g. 1e16 == 1%
    ):
    FRAC = _frac
    HEALTH_THRESHOLD = _health_threshold


@internal
@view
def _x_down(_controller: IController, _user: address) -> uint256:
    # Obtain the value of the users collateral if it
    # was fully soft liquidated into borrowed tokens
    return staticcall (staticcall _controller.amm()).get_x_down(_user)


@external
@view
def users_to_liquidate(_controller: IController, _from: uint256 = 0, _limit: uint256 = 0) -> DynArray[IZap.Position, 1000]:
    """
    @notice Returns users eligible for partial self-liquidation through this zap.
    @param _controller Address of the controller
    @param _from Loan index to start iteration from
    @param _limit Number of loans to inspect (0 = all)
    @return Dynamic array with position info and zap-specific estimates
    """
    # Cached only for readability purposes
    CONTROLLER: IController = _controller

    base_positions: DynArray[IController.Position, 1000] = view.users_with_health(
        CONTROLLER, _from, _limit, HEALTH_THRESHOLD, True, self, False
    )
    out: DynArray[IZap.Position, 1000] = []
    for i: uint256 in range(1000):
        if i == len(base_positions):
            break
        pos: IController.Position = base_positions[i]
        to_repay: uint256 = staticcall CONTROLLER.tokens_to_liquidate(pos.user, FRAC)
        x_down: uint256 = self._x_down(CONTROLLER, pos.user)
        ratio: uint256 = unsafe_div(unsafe_mul(x_down, WAD), pos.debt)
        out.append(
            IZap.Position(
                user=pos.user,
                x=pos.x,
                y=pos.y,
                health=pos.health,
                dx=unsafe_div(pos.y * ctrl._get_f_remove(FRAC, 0), WAD),
                dy=unsafe_div(unsafe_mul(to_repay, ratio), WAD),
            )
        )
    return out


@external
def liquidate_partial(_controller: IController, _user: address, _min_x: uint256):
    """
    @notice Trigger partial self-liquidation of `user` using FRAC.
            Caller supplies borrowed tokens; receives withdrawn collateral.
    @param _controller Address of the controller
    @param _user Address of the position owner (must have approved this zap in controller)
    @param _min_x Minimal x withdrawn from AMM to guard against MEV
    """
    # Cached only for readability purposes
    CONTROLLER: IController = _controller

    BORROWED: IERC20 = staticcall CONTROLLER.borrowed_token()
    COLLATERAL: IERC20 = staticcall CONTROLLER.collateral_token()

    assert staticcall CONTROLLER.approval(_user, self), "not approved"
    assert staticcall CONTROLLER.health(_user, False) < HEALTH_THRESHOLD, "health too high"

    tkn.max_approve(BORROWED, CONTROLLER.address)

    total_debt: uint256 = staticcall CONTROLLER.debt(_user)
    x_down: uint256 = self._x_down(CONTROLLER, _user)
    ratio: uint256 = unsafe_div(unsafe_mul(x_down, WAD), total_debt)

    assert ratio > WAD, "position rekt"

    # Amount of borrowed token the liquidator must supply
    to_repay: uint256 = staticcall CONTROLLER.tokens_to_liquidate(_user, FRAC)
    borrowed_from_sender: uint256 = unsafe_div(unsafe_mul(to_repay, ratio), WAD)

    tkn.transfer_from(BORROWED, msg.sender, self, borrowed_from_sender)

    extcall CONTROLLER.liquidate(_user, _min_x, FRAC)
    collateral_received: uint256 = staticcall COLLATERAL.balanceOf(self)
    tkn.transfer(COLLATERAL, msg.sender, collateral_received)

    # surplus amount goes into position repay
    borrowed_amount: uint256 = staticcall BORROWED.balanceOf(self)
    extcall CONTROLLER.repay(borrowed_amount, _user)

    log IZap.PartialRepay(
        controller=_controller,
        user=_user,
        collateral_decrease=collateral_received,
        borrowed_from_sender=borrowed_from_sender,
        surplus_repaid=borrowed_amount,
    )
