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
CALLDATA_MAX_SIZE: constant(uint256) = c.CALLDATA_MAX_SIZE
CALLBACK_SIGNATURE: constant(bytes4) = method_id("callback_liquidate_partial(bytes)", output_type=bytes4)

FRAC: public(immutable(uint256))                         # fraction of position to repay (1e18 = 100%)
HEALTH_THRESHOLD: public(immutable(int256))              # trigger threshold on controller.health(user, false)

_LEND_FACTORY: immutable(ILendFactory)

@view
@external
def FACTORY() -> address:
    return _LEND_FACTORY.address


@deploy
def __init__(
        _factory: address,
        _frac: uint256,                       # e.g. 5e16 == 5%
        _health_threshold: int256,            # e.g. 1e16 == 1%
    ):
    _LEND_FACTORY = ILendFactory(_factory)
    FRAC = _frac
    HEALTH_THRESHOLD = _health_threshold


@internal
@view
def _x_down(_controller: IController, _user: address) -> uint256:
    # Obtain the value of the users collateral if it
    # was fully soft liquidated into borrowed tokens
    return staticcall (staticcall _controller.amm()).get_x_down(_user)


@internal
@view
def _get_controller(_c_idx: uint256) -> IController:
    return (staticcall _LEND_FACTORY.markets(_c_idx)).controller


@internal
@view
def _check_controller(_controller: address, _c_idx: uint256):
    contract_info: ILendFactory.ContractInfo = staticcall _LEND_FACTORY.check_contract(_controller)
    assert contract_info.contract_type == ILendFactory.ContractType.CONTROLLER, "wrong sender"
    assert contract_info.market_index == _c_idx, "wrong sender"


@internal
@view
def _users_to_liquidate(
    _controller: IController,
    _from: uint256,
    _limit: uint256,
) -> DynArray[IZap.Position, 1000]:
    base_positions: DynArray[IController.Position, 1000] = view.users_with_health(
        _controller, _from, _limit, HEALTH_THRESHOLD, True, self, False
    )
    out: DynArray[IZap.Position, 1000] = []
    for i: uint256 in range(1000):
        if i == len(base_positions):
            break
        pos: IController.Position = base_positions[i]
        to_repay: uint256 = staticcall _controller.tokens_to_liquidate(pos.user, FRAC)
        x_down: uint256 = self._x_down(_controller, pos.user)
        ratio: uint256 = unsafe_div(unsafe_mul(x_down, WAD), pos.debt)
        if ratio < WAD:
            continue  # Skip positions that would fail ration check
        out.append(
            IZap.Position(
                user=pos.user,
                x=pos.x,
                y=pos.y,
                health=pos.health,
                dx=unsafe_div(unsafe_mul(to_repay, ratio), WAD),
                dy=unsafe_div(pos.y * ctrl._get_f_remove(FRAC, 0), WAD),
            )
        )

    return out


@internal
def _liquidate_partial(
    _controller: IController,
    _c_idx: uint256,
    _user: address,
    _min_x: uint256,
    _exchange_contract: address = empty(address),
    _exchange_calldata: Bytes[CALLDATA_MAX_SIZE - 32 * 5] = b"",
):
    borrowed_token: IERC20 = staticcall _controller.borrowed_token()
    collateral_token: IERC20 = staticcall _controller.collateral_token()

    assert staticcall _controller.approval(_user, self), "not approved"
    assert staticcall _controller.health(_user, False) < HEALTH_THRESHOLD, "health too high"

    total_debt: uint256 = staticcall _controller.debt(_user)
    x_down: uint256 = self._x_down(_controller, _user)
    ratio: uint256 = unsafe_div(unsafe_mul(x_down, WAD), total_debt)

    assert ratio > WAD, "position rekt"

    # Amount of borrowed token the liquidator must supply
    to_repay: uint256 = staticcall _controller.tokens_to_liquidate(_user, FRAC)
    borrowed_from_sender: uint256 = unsafe_div(unsafe_mul(to_repay, ratio), WAD)

    tkn.max_approve(borrowed_token, _controller.address)
    if _exchange_contract != empty(address):
        tkn.max_approve(collateral_token, _exchange_contract)
        liquidate_calldata: Bytes[CALLDATA_MAX_SIZE] = abi_encode(_c_idx, borrowed_from_sender, _exchange_contract, _exchange_calldata)
        extcall _controller.liquidate(_user, _min_x, FRAC, self, liquidate_calldata)
    else:
        tkn.transfer_from(borrowed_token, msg.sender, self, borrowed_from_sender)
        extcall _controller.liquidate(_user, _min_x, FRAC)

    # surplus borrowed amount goes into position repay
    extcall _controller.repay(borrowed_from_sender - to_repay, _user)

    tkn.transfer(borrowed_token, msg.sender, staticcall borrowed_token.balanceOf(self))
    tkn.transfer(collateral_token, msg.sender, staticcall collateral_token.balanceOf(self))

    log IZap.PartialRepay(
        controller=_controller,
        user=_user,
        borrowed_from_sender=borrowed_from_sender,
        surplus_repaid=borrowed_from_sender - to_repay,
    )


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
    return self._users_to_liquidate(
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
    _exchange_calldata: Bytes[CALLDATA_MAX_SIZE - 32 * 5] = b"",
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
    self._liquidate_partial(
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
    _calldata: Bytes[CALLDATA_MAX_SIZE],
) -> uint256[2]:
    """
    @notice Controller callback invoked during liquidate.
    @dev Provides borrowed tokens back to controller to cover shortfall and
         forwards collateral to the liquidator via controller.transferFrom.
    """
    c_idx: uint256 = 0
    borrowed_from_sender: uint256 = 0
    exchange_contract: address = empty(address)
    exchange_calldata: Bytes[CALLDATA_MAX_SIZE - 32 * 5] = empty(Bytes[CALLDATA_MAX_SIZE - 32 * 5])

    c_idx, borrowed_from_sender, exchange_contract, exchange_calldata = abi_decode(_calldata, (uint256, uint256, address, Bytes[CALLDATA_MAX_SIZE - 32 * 5]))

    self._check_controller(msg.sender, c_idx)

    raw_call(exchange_contract, exchange_calldata)

    return [borrowed_from_sender, 0]
