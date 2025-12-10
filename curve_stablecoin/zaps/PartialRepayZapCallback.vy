# pragma version 0.4.3

"""
@title LlamaLendPartialRepayZapCallback
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2025 - all rights reserved
@notice Partially repays a position (self-liquidation) when health is low,
        using controller callback to forward assets directly to the caller.
"""

from curve_std.interfaces import IERC20
from curve_stablecoin.interfaces import IAMM
from curve_stablecoin.interfaces import IController
from curve_stablecoin import controller as ctrl
from curve_std import token as tkn
from curve_stablecoin.interfaces import IPartialRepayZapCallback as IZap
import curve_stablecoin.lib.liquidation_lib as liq

from curve_stablecoin import constants as c

implements: IZap

# https://github.com/vyperlang/vyper/issues/4723
WAD: constant(uint256) = c.WAD

FRAC: public(immutable(uint256))                         # fraction of position to repay (1e18 = 100%)
HEALTH_THRESHOLD: public(immutable(int256))              # trigger threshold on controller.health(user, false)

CALLDATA_MAX_SIZE: constant(uint256) = c.CALLDATA_MAX_SIZE
CALLBACK_SIGNATURE: constant(bytes4) = method_id("callback_liquidate_partial(bytes)",output_type=bytes4,)


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

    base_positions: DynArray[IController.Position, 1000] = liq.users_with_health(
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
def liquidate_partial(
    _controller: IController,
    _user: address,
    _min_x: uint256,
    _callbacker: address = empty(address),
    _calldata: Bytes[CALLDATA_MAX_SIZE - 32 * 6] = b"",
):
    """
    @notice Trigger partial self-liquidation of `user` using FRAC.
            Caller supplies borrowed tokens; receives withdrawn collateral.
    @param _controller Address of the controller
    @param _user Address of the position owner (must have approved this zap in controller)
    @param _min_x Minimal x withdrawn from AMM to guard against MEV
    @param _callbacker Address of the callback contract
    @param _calldata Any data for callbacker (address x 3 (64) + uint256 (32) + 2 * offset (32) + must be divided by 32 - slots (16))
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

    if _callbacker != empty(address):
        liquidate_calldata: Bytes[CALLDATA_MAX_SIZE] = abi_encode(_controller.address, _user, borrowed_from_sender, _callbacker, _calldata)
        extcall CONTROLLER.liquidate(_user, _min_x, FRAC, self, liquidate_calldata)

    else:
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
        surplus_repaid=borrowed_amount,
    )


@internal
def execute_callback(
    callbacker: address,
    callback_sig: bytes4,
    calldata: Bytes[CALLDATA_MAX_SIZE - 32 * 6],
):
    response: Bytes[64] = raw_call(
        callbacker,
        concat(
            callback_sig,
            abi_encode(calldata),
        ),
        max_outsize=64,
    )


@external
def callback_liquidate(
    _user: address,
    _borrowed: uint256,
    _collateral: uint256,
    _debt: uint256,
    _calldata: Bytes[CALLDATA_MAX_SIZE],
) -> uint256[2]:
    """
    @notice Controller callback invoked during liquidate.
    @dev Provides borrowed tokens back to controller to cover shortfall and
         forwards collateral to the liquidator via controller.transferFrom.
    """
    controller: address = empty(address)
    user: address = empty(address)
    borrowed_from_sender: uint256 = 0
    callbacker: address = empty(address)
    callbacker_calldata: Bytes[CALLDATA_MAX_SIZE - 32 * 6] = empty(Bytes[CALLDATA_MAX_SIZE - 32 * 6])

    controller, user, borrowed_from_sender, callbacker, callbacker_calldata = abi_decode(_calldata, (address, address, uint256, address, Bytes[CALLDATA_MAX_SIZE - 32 * 6]))
    assert msg.sender == controller, "wrong sender"

    # Cached only for readability purposes
    CONTROLLER: IController = IController(controller)
    BORROWED: IERC20 = staticcall CONTROLLER.borrowed_token()
    COLLATERAL: IERC20 = staticcall CONTROLLER.collateral_token()

    collateral_received: uint256 = staticcall COLLATERAL.balanceOf(self)
    tkn.transfer(COLLATERAL, callbacker, collateral_received)

    self.execute_callback(
        callbacker,
        CALLBACK_SIGNATURE,
        callbacker_calldata
    )

    tkn.transfer_from(BORROWED, callbacker, self, borrowed_from_sender)

    return [borrowed_from_sender, 0]
