# pragma version 0.4.3
# pragma optimize codesize

"""
@title LlamaLend Intents — permissionless CallbackAdapter
@author Curve.Finance
@license Copyright (c) Curve.Finance, 2020-2026 - all rights reserved
@notice Zero-privilege, stateless sandbox for solver-supplied swap routes.
        Implements the controller callback interface (callback_deposit /
        callback_repay / callback_liquidate). Holds no approvals from users
        and no balances between transactions — the worst a malicious route
        can do is fill at the intent's signed price floor, which the
        executor enforces via position deltas after the fill.
@dev calldata layout: abi_encode(route_target: address, route_data: Bytes).
     Token addresses are read from msg.sender (the controller). No router
     whitelist by design (aggregator-independent).
@custom:security security@curve.finance
"""

from curve_std.interfaces import IERC20
from curve_stablecoin.interfaces import IController


CALLDATA_MAX: constant(uint256) = 4096
ROUTE_DATA_MAX: constant(uint256) = 3968  # CALLDATA_MAX - abi overhead
MAX_UINT: constant(uint256) = max_value(uint256)


@internal
def _swap(_target: address, _data: Bytes[ROUTE_DATA_MAX], _token_in: IERC20):
    bal: uint256 = staticcall _token_in.balanceOf(self)
    if bal > 0:
        assert extcall _token_in.approve(_target, bal, default_return_value=True)
    raw_call(_target, _data)
    # drop leftover allowance
    assert extcall _token_in.approve(_target, 0, default_return_value=True)


@internal
def _approve_all(_token: IERC20, _spender: address) -> uint256:
    bal: uint256 = staticcall _token.balanceOf(self)
    assert extcall _token.approve(_spender, bal, default_return_value=True)
    return bal


@external
@nonreentrant
def callback_deposit(
    _user: address,
    _borrowed: uint256,
    _user_collateral: uint256,
    _d_debt: uint256,
    _calldata: Bytes[CALLDATA_MAX],
) -> uint256[2]:
    """
    @notice Leverage: controller sent `_d_debt` borrowed tokens here;
            swap them into collateral via the solver route.
    @return [0, leverage_collateral]
    """
    ctrl: IController = IController(msg.sender)
    borrowed_token: IERC20 = staticcall ctrl.borrowed_token()
    collateral_token: IERC20 = staticcall ctrl.collateral_token()

    target: address = empty(address)
    data: Bytes[ROUTE_DATA_MAX] = b""
    target, data = abi_decode(_calldata, (address, Bytes[ROUTE_DATA_MAX]))

    self._swap(target, data, borrowed_token)

    # unused borrowed goes back to the user (allowed by controller flow)
    leftover: uint256 = staticcall borrowed_token.balanceOf(self)
    if leftover > 0:
        assert extcall borrowed_token.transfer(
            _user, leftover, default_return_value=True
        )

    collateral: uint256 = self._approve_all(collateral_token, msg.sender)
    return [0, collateral]


@external
@nonreentrant
def callback_repay(
    _user: address,
    _borrowed: uint256,
    _collateral: uint256,
    _debt: uint256,
    _calldata: Bytes[CALLDATA_MAX],
) -> uint256[2]:
    """
    @notice Delever: controller sent position collateral here; swap it into
            borrowed tokens via the solver route.
    @return [borrowed_from_state_collateral, remaining_collateral]
    """
    ctrl: IController = IController(msg.sender)
    borrowed_token: IERC20 = staticcall ctrl.borrowed_token()
    collateral_token: IERC20 = staticcall ctrl.collateral_token()

    target: address = empty(address)
    data: Bytes[ROUTE_DATA_MAX] = b""
    target, data = abi_decode(_calldata, (address, Bytes[ROUTE_DATA_MAX]))

    self._swap(target, data, collateral_token)

    borrowed_out: uint256 = self._approve_all(borrowed_token, msg.sender)
    collateral_left: uint256 = self._approve_all(collateral_token, msg.sender)
    return [borrowed_out, collateral_left]


@external
@nonreentrant
def callback_liquidate(
    _user: address,
    _stablecoins: uint256,
    _collateral: uint256,
    _debt: uint256,
    _calldata: Bytes[CALLDATA_MAX],
) -> uint256[2]:
    """
    @notice Same shape as callback_repay, used by controller.liquidate.
    """
    ctrl: IController = IController(msg.sender)
    borrowed_token: IERC20 = staticcall ctrl.borrowed_token()
    collateral_token: IERC20 = staticcall ctrl.collateral_token()

    target: address = empty(address)
    data: Bytes[ROUTE_DATA_MAX] = b""
    target, data = abi_decode(_calldata, (address, Bytes[ROUTE_DATA_MAX]))

    self._swap(target, data, collateral_token)

    borrowed_out: uint256 = self._approve_all(borrowed_token, msg.sender)
    collateral_left: uint256 = self._approve_all(collateral_token, msg.sender)
    return [borrowed_out, collateral_left]
