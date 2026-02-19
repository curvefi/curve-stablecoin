# pragma version 0.4.3

"""
@title LlamaLendPartialRepayZap
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2025 - all rights reserved
@notice Partially repays a position (self-liquidation) when health is low,
        using controller callback to forward assets directly to the caller.
"""

from curve_std.interfaces import IERC20
from curve_stablecoin.interfaces import IController
from curve_stablecoin.interfaces import ILendFactory
from curve_stablecoin import controller as ctrl
from curve_stablecoin import ControllerView as view
from curve_std import token as tkn
from curve_stablecoin.interfaces import IPartialRepayZap as IZap

from curve_stablecoin import constants as c

implements: IZap

# https://github.com/vyperlang/vyper/issues/4723
WAD: constant(uint256) = c.WAD

FACTORY: public(immutable(ILendFactory))
FRAC: public(immutable(uint256))                         # fraction of position to repay (1e18 = 100%)
HEALTH_THRESHOLD: public(immutable(int256))              # trigger threshold on controller.health(user, false)

CALLDATA_MAX_SIZE: constant(uint256) = c.CALLDATA_MAX_SIZE
CALLBACK_SIGNATURE: constant(bytes4) = method_id("callback_liquidate_partial(bytes)", output_type=bytes4)


@deploy
def __init__(
        _factory: ILendFactory,
        _frac: uint256,                       # e.g. 5e16 == 5%
        _health_threshold: int256,            # e.g. 1e16 == 1%
    ):
    FACTORY = _factory
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
    CONTROLLER: IController = (staticcall FACTORY.markets(_c_idx)).controller

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
        if ratio < WAD:
            continue  # Skip positions that would fail ration check
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
    _c_idx: uint256,
    _user: address,
    _min_x: uint256,
    _callbacker: address = empty(address),
    _calldata: Bytes[CALLDATA_MAX_SIZE - 32 * 6] = b"",
):
    """
    @notice Trigger partial self-liquidation of `user` using FRAC.
            Caller supplies borrowed tokens; receives withdrawn collateral.
    @param _c_idx Index of the market in the factory
    @param _user Address of the position owner (must have approved this zap in controller)
    @param _min_x Minimal x withdrawn from AMM to guard against MEV
    @param _callbacker Address of the callback contract
    @param _calldata Any data for callbacker (address x 2 (64) + uint256 (32) + 2 * offset (32) + must be divided by 32 - slots (16))
    """
    controller: IController = (staticcall FACTORY.markets(_c_idx)).controller

    borrowed_token: IERC20 = staticcall controller.borrowed_token()
    collateral_token: IERC20 = staticcall controller.collateral_token()

    assert staticcall controller.approval(_user, self), "not approved"
    assert staticcall controller.health(_user, False) < HEALTH_THRESHOLD, "health too high"

    tkn.max_approve(borrowed_token, controller.address)

    total_debt: uint256 = staticcall controller.debt(_user)
    x_down: uint256 = self._x_down(controller, _user)
    ratio: uint256 = unsafe_div(unsafe_mul(x_down, WAD), total_debt)

    assert ratio > WAD, "position rekt"

    # Amount of borrowed token the liquidator must supply
    to_repay: uint256 = staticcall controller.tokens_to_liquidate(_user, FRAC)
    borrowed_from_sender: uint256 = unsafe_div(unsafe_mul(to_repay, ratio), WAD)

    if _callbacker != empty(address):
        liquidate_calldata: Bytes[CALLDATA_MAX_SIZE] = abi_encode(_c_idx, _user, borrowed_from_sender, _callbacker, _calldata)
        extcall controller.liquidate(_user, _min_x, FRAC, self, liquidate_calldata)

    else:
        tkn.transfer_from(borrowed_token, msg.sender, self, borrowed_from_sender)

        extcall controller.liquidate(_user, _min_x, FRAC)
        collateral_received: uint256 = staticcall collateral_token.balanceOf(self)
        tkn.transfer(collateral_token, msg.sender, collateral_received)

    # surplus amount goes into position repay
    borrowed_amount: uint256 = staticcall borrowed_token.balanceOf(self)
    extcall controller.repay(borrowed_amount, _user)

    log IZap.PartialRepay(
        controller=controller,
        user=_user,
        borrowed_from_sender=borrowed_from_sender,
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
    c_idx: uint256 = 0
    user: address = empty(address)
    borrowed_from_sender: uint256 = 0
    callbacker: address = empty(address)
    callbacker_calldata: Bytes[CALLDATA_MAX_SIZE - 32 * 6] = empty(Bytes[CALLDATA_MAX_SIZE - 32 * 6])

    c_idx, user, borrowed_from_sender, callbacker, callbacker_calldata = abi_decode(_calldata, (uint256, address, uint256, address, Bytes[CALLDATA_MAX_SIZE - 32 * 6]))

    contract_info: ILendFactory.ContractInfo = staticcall FACTORY.check_contract(msg.sender)
    assert contract_info.contract_type == ILendFactory.ContractType.CONTROLLER, "wrong sender"
    assert contract_info.market_index == c_idx, "wrong sender"
    controller: IController = IController(msg.sender)
    borrowed_token: IERC20 = staticcall controller.borrowed_token()
    collateral_token: IERC20 = staticcall controller.collateral_token()

    collateral_received: uint256 = staticcall collateral_token.balanceOf(self)
    tkn.transfer(collateral_token, callbacker, collateral_received)

    self.execute_callback(
        callbacker,
        CALLBACK_SIGNATURE,
        callbacker_calldata
    )

    tkn.transfer_from(borrowed_token, callbacker, self, borrowed_from_sender)

    return [borrowed_from_sender, 0]
