# pragma version 0.4.3
# pragma nonreentrancy on
# pragma optimize codesize

"""
@title LlamaLendPartialRepayZap
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2025 - all rights reserved
@notice Partially repays a position (self-liquidation) when health is low.
        Liquidator provides borrowed tokens, receives withdrawn collateral.
"""

from ethereum.ercs import IERC20
from contracts.interfaces import IAMM
from contracts.interfaces import ILlamalendController as IController

from contracts import constants as c

WAD: constant(uint256) = c.WAD

CONTROLLER: public(immutable(IController))
AMM: public(immutable(IAMM))
BORROWED: public(immutable(IERC20))
COLLATERAL: public(immutable(IERC20))

FRAC: public(immutable(uint256))                         # fraction of position to repay (1e18 = 100%)
HEALTH_THRESHOLD: public(immutable(int256))              # trigger threshold on controller.health(user, false)


struct Position:
    user: address
    x: uint256
    y: uint256
    health: int256
    dx: uint256  # collateral estimated to be withdrawn for FRAC
    dy: uint256  # borrowed needed for FRAC


@deploy
def __init__(
        _controller: address,
        _amm: address,
        _borrowed: address,
        _collateral: address,
        _frac: uint256,                       # e.g. 5e16 == 5%
        _health_threshold: int256,            # e.g. 1e16 == 1%
    ):
    CONTROLLER = IController(_controller)
    AMM = IAMM(_amm)
    BORROWED = IERC20(_borrowed)
    COLLATERAL = IERC20(_collateral)

    FRAC = _frac
    HEALTH_THRESHOLD = _health_threshold

    self._approve(BORROWED, _controller)
    self._approve(COLLATERAL, _controller)


@internal
def _approve(token: IERC20, spender: address):
    if staticcall token.allowance(self, spender) == 0:
        assert extcall token.approve(spender, max_value(uint256), default_return_value=True)


@internal
def _transferFrom(token: IERC20, _from: address, _to: address, amount: uint256):
    if amount > 0:
        assert extcall token.transferFrom(_from, _to, amount, default_return_value=True)


@internal
@pure
def _get_f_remove(frac: uint256, health_limit: uint256) -> uint256:
    # f_remove = ((1 + h / 2) / (1 + h) * (1 - frac) + frac) * frac
    f_remove: uint256 = WAD
    if frac < WAD:
        f_remove = unsafe_div(
            unsafe_mul(
                unsafe_add(WAD, unsafe_div(health_limit, 2)),
                unsafe_sub(WAD, frac),
            ),
            unsafe_add(WAD, health_limit),
        )
        f_remove = unsafe_div(unsafe_mul(unsafe_add(f_remove, frac), frac), WAD)

    return f_remove

# @external
# @view
# def users_to_liquidate(_from: uint256 = 0, _limit: uint256 = 0) -> DynArray[Position, 1000]:
#     """
#     @notice Returns users eligible for partial self-liquidation through this zap.
#     @param _from Loan index to start iteration from
#     @param _limit Number of loans to inspect (0 = all)
#     @return Dynamic array with position info and zap-specific estimates
#     """
#     n_loans: uint256 = CONTROLLER.n_loans()
#     limit: uint256 = _limit if _limit != 0 else n_loans
#     ix: uint256 = _from
#     out: DynArray[Position, 1000] = []
#     for i in range(10**6):
#         if ix >= n_loans or i == limit:
#             break
#         user: address = CONTROLLER.loans(ix)
#         h: int256 = CONTROLLER.health(user, False)
#         if CONTROLLER.approval(user, self) and h < HEALTH_THRESHOLD:
#             xy: uint256[2] = AMM.get_sum_xy(user)
#             dx: uint256 = self._collateral_from_liquidate(h, xy[1])
#             dy: uint256 = CONTROLLER.tokens_to_liquidate(user, FRAC)
#             out.append(Position({
#                 user: user,
#                 x: xy[0],
#                 y: xy[1],
#                 health: h,
#                 dx: dx,
#                 dy: dy,
#             }))
#         ix += 1
#     return out


@external
def repay_from_position(user: address, min_x: uint256):
    """
    @notice Trigger partial self-liquidation of `user` using FRAC.
            Caller supplies borrowed tokens; receives withdrawn collateral.
    @param user Address of the position owner (must have approved this zap in controller)
    @param min_x Minimal x withdrawn from AMM to guard against MEV
    """
    assert staticcall CONTROLLER.approval(user, self), "not approved"
    assert staticcall CONTROLLER.health(user, False) < HEALTH_THRESHOLD, "health too high"

    total_debt: uint256 = staticcall CONTROLLER.debt(user)
    x_down: uint256 = staticcall AMM.get_x_down(user)
    ratio: uint256 = unsafe_div(unsafe_mul(x_down, 10 ** 18), total_debt)

    assert ratio > 10 ** 18, "position rekt"

    # Amount of borrowed token the liquidator must supply
    to_repay: uint256 = staticcall CONTROLLER.tokens_to_liquidate(user, FRAC)
    borrowed_from_sender: uint256 = unsafe_sub(unsafe_mul(to_repay, ratio), 10 ** 18)

    self._transferFrom(BORROWED, msg.sender, self, borrowed_from_sender)

    extcall CONTROLLER.liquidate(user, min_x, FRAC, empty(address), b"")
    collateral_received: uint256 = staticcall COLLATERAL.balanceOf(self)
    self._transferFrom(COLLATERAL, self, msg.sender, collateral_received)

    # sulprus amount goes into position repay
    borrowed_amount: uint256 = staticcall BORROWED.balanceOf(self)
    extcall CONTROLLER.repay(borrowed_amount, user, max_value(int256), empty(address), b"")
