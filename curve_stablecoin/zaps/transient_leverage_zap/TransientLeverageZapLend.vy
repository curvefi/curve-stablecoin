# pragma version 0.4.3
# pragma optimize codesize

"""
@title LlamaLend V2 Lend Markets TransientLeverageZap
@author Curve.Finance
@license Copyright (c) Curve.Finance, 2020-2026 - all rights reserved
@notice Creates leverage on LlamaLend V2 markets via whitelisted Aggregator Routers.
        Unlike LeverageZapLend, the zap itself is the entry point: the swap parameters
        are parked in transient storage for the duration of the controller call rather
        than being routed through the controller as `calldata`. Aggregator routes are
        therefore not capped by the controller's CALLDATA_MAX_SIZE. In exchange the
        user has to approve the zap on the controller, since the zap acts for them.
@custom:security security@curve.finance
@custom:kill Set is_approved_exchange False for all the exchanges.
"""

from curve_stablecoin.interfaces import IAMM
from curve_stablecoin.interfaces import ILendFactory
from curve_stablecoin.interfaces import IController
from curve_stablecoin import ControllerView
from curve_stablecoin.interfaces import ILeverageZap
from curve_stablecoin.interfaces import ITransientLeverageZap
from curve_std.interfaces import IERC20
from curve_std import token as tkn
from snekmate.utils import math

version: public(constant(String[5])) = "1.0.0"

implements: ITransientLeverageZap

################################################################
#                          CONSTANTS                           #
################################################################

from curve_stablecoin import constants as c
from curve_stablecoin.zaps.transient_leverage_zap import transient_leverage_zap_constants as zc

WAD: constant(uint256) = c.WAD
DEAD_SHARES: constant(uint256) = c.DEAD_SHARES
MAX_TICKS_UINT: constant(uint256) = c.MAX_TICKS_UINT
EXCHANGE_CALLDATA_MAX_SIZE: constant(uint256) = zc.EXCHANGE_CALLDATA_MAX_SIZE
CALLBACK_CALLDATA_MAX_SIZE: constant(uint256) = zc.CALLBACK_CALLDATA_MAX_SIZE

_LEND_FACTORY: immutable(ILendFactory)

MAX_INIT_EXCHANGES: constant(uint256) = 10

# Whitelist of exchanges (routers/pools) the zap is allowed to `raw_call`
is_approved_exchange: public(HashMap[address, bool])

################################################################
#                       STASHED PARAMS                         #
################################################################
# Set by an entry point right before it calls the controller, read back by the
# callback the controller makes into this zap, cleared when the call returns.
# Transient storage is wiped at the end of the transaction anyway.

# Controller of the call this zap started. Non-empty only while that call is running,
# so it is both the callback's authentication and the entry points' reentrancy guard.
stashed_controller: transient(address)
stashed_exchange: transient(address)
stashed_min_recv: transient(uint256)
stashed_calldata: transient(Bytes[EXCHANGE_CALLDATA_MAX_SIZE])
# Balance the zap held when the entry point handed over to the controller: user funds
# parked here for the controller to pull, plus any dust. The callback measures swap
# output against it, so parked funds can never be counted as exchange proceeds.
stashed_held: transient(uint256)


@deploy
def __init__(_factory: address, _exchanges: DynArray[address, MAX_INIT_EXCHANGES]):
    """
    @notice Contract constructor
    @param _factory Address of the factory the zap is associated with (used to look up controllers and the admin)
    @param _exchanges Initial list of exchanges (routers/pools) to add to the whitelist
    """
    _LEND_FACTORY = ILendFactory(_factory)

    for exchange: address in _exchanges:
        self._set_exchange(exchange, True)


################################################################
#                       CALCULATIONS                           #
################################################################


@internal
@view
def _get_k_effective(_controller: IController, _collateral: uint256, _N: uint256) -> uint256:
    """
    @notice Intermediary method which calculates k_effective defined as x_effective / p_base / y,
            however discounted by loan_discount.
            x_effective is an amount which can be obtained from collateral when liquidating
    @param _controller Controller of the market
    @param _collateral Total collateral deposited into the bands
    @param _N Number of bands the deposit is made into
    @return k_effective
    """
    # x_effective = sum_{i=0..N-1}(y / N * p(n_{n1+i})) =
    # = y / N * p_oracle_up(n1) * sqrt((A - 1) / A) * sum_{0..N-1}(((A-1) / A)**k)
    # === d_y_effective * p_oracle_up(n1) * sum(...) === y * k_effective * p_oracle_up(n1)
    # d_k_effective = 1 / N / sqrt(A / (A - 1))
    # d_k_effective: uint256 = 10**18 * unsafe_sub(10**18, discount) / (SQRT_BAND_RATIO * N)
    # Make some extra discount to always deposit lower when we have DEAD_SHARES rounding
    A: uint256 = staticcall (staticcall _controller.amm()).A()
    SQRT_BAND_RATIO: uint256 = isqrt(unsafe_div(10 ** 36 * A, unsafe_sub(A, 1)))

    discount: uint256 = staticcall _controller.loan_discount()
    d_k_effective: uint256 = WAD * unsafe_sub(
        WAD, min(discount + (DEAD_SHARES * WAD) // max(_collateral // _N, DEAD_SHARES), WAD)
    ) // (SQRT_BAND_RATIO * _N)
    k_effective: uint256 = d_k_effective
    for _: uint256 in range(1, _N, bound=MAX_TICKS_UINT):
        d_k_effective = unsafe_div(d_k_effective * (A - 1), A)
        k_effective = unsafe_add(k_effective, d_k_effective)
    return k_effective


@external
@view
def max_borrowable(
        _controller: IController,
        _user_collateral: uint256,
        _leverage_collateral: uint256,
        _N: uint256,
        _p_avg: uint256,
) -> uint256:
    """
    @notice Calculation of maximum which can be borrowed with leverage
    @param _controller Controller of the market
    @param _user_collateral Amount of collateral token provided by the user
    @param _leverage_collateral Amount of collateral token obtained from leverage (borrowed swapped to collateral)
    @param _N Number of bands the deposit is made into
    @param _p_avg Average price of collateral in borrowed token expected from the leverage swap
    @return Maximum amount of borrowed token that can be borrowed with leverage
    """
    # max_borrowable = collateral / (1 / (k_effective * max_p_base) - 1 / p_avg)
    amm: IAMM = staticcall _controller.amm()
    borrowed_token: IERC20 = IERC20(staticcall amm.coins(0))
    collateral_token: IERC20 = IERC20(staticcall amm.coins(1))
    borrowed_precision: uint256 = pow_mod256(10, convert(18 - staticcall borrowed_token.decimals(), uint256))
    collateral_precision: uint256 = pow_mod256(10, convert(18 - staticcall collateral_token.decimals(), uint256))

    user_collateral: uint256 = _user_collateral * collateral_precision
    leverage_collateral: uint256 = _leverage_collateral * collateral_precision
    k_effective: uint256 = self._get_k_effective(_controller, user_collateral + leverage_collateral, _N)

    A: uint256 = staticcall amm.A()
    max_p_base: uint256 = ControllerView._max_p_base(amm, math._wad_ln(convert(A * WAD // (A - 1), int256)))
    max_borrowable: uint256 = user_collateral * WAD // (10**36 // k_effective * WAD // max_p_base - 10**36 // _p_avg)
    max_borrowable = max_borrowable // borrowed_precision

    return min(max_borrowable, staticcall _controller.available_balance()) # Cannot borrow beyond the amount of coins Controller has


################################################################
#                       STASH HANDLING                         #
################################################################


@internal
def _stash(
        _controller: address,
        _min_recv: uint256,
        _exchange_address: address,
        _exchange_calldata: Bytes[EXCHANGE_CALLDATA_MAX_SIZE],
        _held: uint256,
):
    """
    @notice Park the swap parameters for the controller call which is about to be made
    @dev The entry points cannot use `@nonreentrant`: the callback takes that lock while
         the entry point is still on the stack. A non-empty `stashed_controller` guards
         them instead - it is only set while a call started here is running.
    """
    assert self.stashed_controller == empty(address), "Reentrancy"
    assert _controller != empty(address)  # dev: would leave the callback unguarded

    self.stashed_controller = _controller
    self.stashed_min_recv = _min_recv
    self.stashed_exchange = _exchange_address
    self.stashed_calldata = _exchange_calldata
    self.stashed_held = _held


@internal
def _unstash():
    self.stashed_controller = empty(address)
    self.stashed_min_recv = 0
    self.stashed_exchange = empty(address)
    self.stashed_calldata = b""
    self.stashed_held = 0


@internal
@view
def _stashed_controller() -> address:
    """
    @notice Controller of the call this zap started, asserting that it is the caller
    @dev Empty outside of an entry point, so the callbacks cannot be called from
         anywhere else - including through a controller the zap was not talking to
    @return Address of the controller
    """
    controller: address = self.stashed_controller
    assert msg.sender == controller and controller != empty(address), "wrong controller"
    return controller


################################################################
#                          CALLBACKS                           #
################################################################


@internal
def _execute_raw_call(_token: IERC20, _exchange_address: address, _exchange_calldata: Bytes[EXCHANGE_CALLDATA_MAX_SIZE]):
    assert self.is_approved_exchange[_exchange_address], "Exchange not approved"

    # Approve, call the exchange, then revoke so it retains no allowance afterwards
    assert extcall _token.approve(_exchange_address, max_value(uint256), default_return_value=True)
    raw_call(_exchange_address, _exchange_calldata)
    assert extcall _token.approve(_exchange_address, 0, default_return_value=True)


@external
@nonreentrant
def callback_deposit(
        _user: address,
        _borrowed: uint256,
        _user_collateral: uint256,
        _d_debt: uint256,
        _calldata: Bytes[CALLBACK_CALLDATA_MAX_SIZE],
) -> uint256[2]:
    """
    @notice Callback method called by the controller to create a leveraged position
    @dev Only reachable from a controller call started by this zap's own entry points
    @param _user Address of the user
    @param _borrowed Always 0
    @param _user_collateral The amount of collateral token provided by user (unused)
    @param _d_debt The amount to be borrowed (in addition to what has already been borrowed)
    @param _calldata Unused, always empty - the swap parameters are stashed instead
    @return [0, leverage_collateral]
    """
    controller: address = self._stashed_controller()
    amm: IAMM = staticcall IController(controller).amm()
    borrowed_token: IERC20 = IERC20(staticcall amm.coins(0))
    collateral_token: IERC20 = IERC20(staticcall amm.coins(1))

    tkn.max_approve(collateral_token, controller)

    # Buy leverage_collateral for d_debt
    # The amount to be spent is specified inside the exchange_calldata.
    self._execute_raw_call(borrowed_token, self.stashed_exchange, self.stashed_calldata)

    # Everything the zap held before the swap belongs to the user, not to the exchange
    leverage_collateral: uint256 = (staticcall collateral_token.balanceOf(self)) - self.stashed_held
    assert leverage_collateral >= self.stashed_min_recv, "Slippage"

    log ILeverageZap.Deposit(
        controller=controller,
        user=_user,
        leverage_collateral=leverage_collateral,
        d_debt=_d_debt,
    )

    # Borrowed tokens the exchange didn't spend stay here and are refunded by the entry
    # point (the controller requires the returned borrowed amount to be 0).
    return [0, leverage_collateral]


@external
@nonreentrant
def callback_repay(
        _user: address,
        _borrowed: uint256,
        _collateral: uint256,
        _debt: uint256,
        _calldata: Bytes[CALLBACK_CALLDATA_MAX_SIZE],
) -> uint256[2]:
    """
    @notice Callback method called by the controller to deleverage/repay a position
            using collateral from the user's position
    @dev Only reachable from a controller call started by this zap's own entry points
    @param _user Address of the user
    @param _borrowed The value from user_state
    @param _collateral The value from user_state
    @param _debt The value from user_state
    @param _calldata Unused, always empty - the swap parameters are stashed instead
    @return [borrowed_from_state_collateral, remaining_collateral]
    """
    controller: address = self._stashed_controller()
    amm: IAMM = staticcall IController(controller).amm()
    borrowed_token: IERC20 = IERC20(staticcall amm.coins(0))
    collateral_token: IERC20 = IERC20(staticcall amm.coins(1))

    initial_collateral: uint256 = staticcall collateral_token.balanceOf(self)

    tkn.max_approve(borrowed_token, controller)
    tkn.max_approve(collateral_token, controller)

    # Buy borrowed token for collateral from user's position.
    # The amount to be spent is specified inside the exchange_calldata.
    self._execute_raw_call(collateral_token, self.stashed_exchange, self.stashed_calldata)

    remaining_collateral: uint256 = staticcall collateral_token.balanceOf(self)
    # Everything the zap held before the swap belongs to the user, not to the exchange
    borrowed_from_state_collateral: uint256 = (staticcall borrowed_token.balanceOf(self)) - self.stashed_held
    assert borrowed_from_state_collateral >= self.stashed_min_recv, "Slippage"
    assert remaining_collateral < initial_collateral, "Collateral must decrease"
    state_collateral_used: uint256 = initial_collateral - remaining_collateral

    log ILeverageZap.Repay(
        controller=controller,
        user=_user,
        state_collateral_used=state_collateral_used,
        borrowed_from_state_collateral=borrowed_from_state_collateral,
    )

    return [borrowed_from_state_collateral, remaining_collateral]


################################################################
#                        ENTRY POINTS                          #
################################################################


@internal
def _refund(_amm: IAMM):
    """
    @notice Return everything the zap is left holding to the caller
    """
    for i: uint256 in range(2):
        token: IERC20 = IERC20(staticcall _amm.coins(i))
        tkn.transfer(token, msg.sender, staticcall token.balanceOf(self))


@internal
def _create_loan(
        _controller: IController,
        _collateral: uint256,
        _debt: uint256,
        _N: uint256,
        _min_recv: uint256,
        _exchange_address: address,
        _exchange_calldata: Bytes[EXCHANGE_CALLDATA_MAX_SIZE],
):
    amm: IAMM = staticcall _controller.amm()
    collateral_token: IERC20 = IERC20(staticcall amm.coins(1))

    # The controller pulls `_collateral` from us (we are its `msg.sender`), so it has
    # to be here before the call, parked rather than swapped - see `stashed_held`.
    tkn.transfer_from(collateral_token, msg.sender, self, _collateral)
    self._stash(
        _controller.address,
        _min_recv,
        _exchange_address,
        _exchange_calldata,
        staticcall collateral_token.balanceOf(self),
    )

    extcall _controller.create_loan(_collateral, _debt, _N, msg.sender, self, b"")

    self._unstash()
    self._refund(amm)


@internal
def _borrow_more(
        _controller: IController,
        _collateral: uint256,
        _debt: uint256,
        _min_recv: uint256,
        _exchange_address: address,
        _exchange_calldata: Bytes[EXCHANGE_CALLDATA_MAX_SIZE],
):
    amm: IAMM = staticcall _controller.amm()
    collateral_token: IERC20 = IERC20(staticcall amm.coins(1))

    tkn.transfer_from(collateral_token, msg.sender, self, _collateral)
    self._stash(
        _controller.address,
        _min_recv,
        _exchange_address,
        _exchange_calldata,
        staticcall collateral_token.balanceOf(self),
    )

    extcall _controller.borrow_more(_collateral, _debt, msg.sender, self, b"")

    self._unstash()
    self._refund(amm)


@internal
def _repay(
        _controller: IController,
        _wallet_d_debt: uint256,
        _max_active_band: int256,
        _min_recv: uint256,
        _exchange_address: address,
        _exchange_calldata: Bytes[EXCHANGE_CALLDATA_MAX_SIZE],
        _shrink: bool,
):
    amm: IAMM = staticcall _controller.amm()
    borrowed_token: IERC20 = IERC20(staticcall amm.coins(0))
    collateral_token: IERC20 = IERC20(staticcall amm.coins(1))

    # The controller sends the position's collateral here and takes back whatever the
    # swap left, refusing to take back more than it sent. Collateral already sitting
    # here would be part of that leftover, so it has to go before the call - otherwise
    # dust exceeding the swapped amount reverts the repay.
    tkn.transfer(collateral_token, msg.sender, staticcall collateral_token.balanceOf(self))

    # Whatever the swap does not cover is pulled from us by the controller, so the
    # wallet part of the repayment has to be here before the call. What is left over
    # (a full repay only takes the shortfall) is refunded at the end. Capped at the
    # debt so that `max_value(uint256)` keeps meaning "as much as needed".
    wallet_d_debt: uint256 = min(_wallet_d_debt, staticcall _controller.debt(msg.sender))
    tkn.transfer_from(borrowed_token, msg.sender, self, wallet_d_debt)
    self._stash(
        _controller.address,
        _min_recv,
        _exchange_address,
        _exchange_calldata,
        staticcall borrowed_token.balanceOf(self),
    )

    extcall _controller.repay(wallet_d_debt, msg.sender, _max_active_band, self, b"", _shrink)

    self._unstash()
    self._refund(amm)


@external
def create_loan(
        _controller_id: uint256,
        _collateral: uint256,
        _debt: uint256,
        _N: uint256,
        _min_recv: uint256,
        _exchange_address: address,
        _exchange_calldata: Bytes[EXCHANGE_CALLDATA_MAX_SIZE],
):
    """
    @notice Create a leveraged position
    @dev Requires `controller.approve(zap, True)` from the caller, since the zap
         creates the loan on their behalf
    @param _controller_id Index of the market in the factory
    @param _collateral Amount of collateral token provided by the caller
    @param _debt Amount to borrow and swap for collateral
    @param _N Number of bands to deposit into
    @param _min_recv Minimum amount of collateral to receive from the exchange
    @param _exchange_address Address of the exchange (e. g. pool, router) to swap borrowed -> collateral
    @param _exchange_calldata Data for the exchange
    """
    self._create_loan(
        (staticcall _LEND_FACTORY.markets(_controller_id)).controller,
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
        _exchange_calldata: Bytes[EXCHANGE_CALLDATA_MAX_SIZE],
):
    """
    @notice Increase leverage on an existing position
    @dev Requires `controller.approve(zap, True)` from the caller
    @param _controller_id Index of the market in the factory
    @param _collateral Amount of collateral token provided by the caller
    @param _debt Amount to borrow and swap for collateral
    @param _min_recv Minimum amount of collateral to receive from the exchange
    @param _exchange_address Address of the exchange (e. g. pool, router) to swap borrowed -> collateral
    @param _exchange_calldata Data for the exchange
    """
    self._borrow_more(
        (staticcall _LEND_FACTORY.markets(_controller_id)).controller,
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
        _exchange_calldata: Bytes[EXCHANGE_CALLDATA_MAX_SIZE],
        _max_active_band: int256 = max_value(int256),
        _shrink: bool = False,
):
    """
    @notice Deleverage a position, selling its collateral for the borrowed token
    @dev Requires `controller.approve(zap, True)` from the caller. `_wallet_d_debt` is
         pulled from the caller up front, capped at the outstanding debt, so
         `max_value(uint256)` means "as much as needed". A full repay only consumes the
         part the swap did not cover; the rest is refunded.
    @param _controller_id Index of the market in the factory
    @param _wallet_d_debt Amount of borrowed token the caller adds from their wallet
    @param _min_recv Minimum amount of borrowed token to receive from the exchange
    @param _exchange_address Address of the exchange (e. g. pool, router) to swap collateral -> borrowed
    @param _exchange_calldata Data for the exchange
    @param _max_active_band Don't allow active band to be higher than this (to prevent front-running the repay)
    @param _shrink Whether to shrink the soft-liquidated part of the position
    """
    self._repay(
        (staticcall _LEND_FACTORY.markets(_controller_id)).controller,
        _wallet_d_debt,
        _max_active_band,
        _min_recv,
        _exchange_address,
        _exchange_calldata,
        _shrink,
    )


################################################################
#                            ADMIN                             #
################################################################


@external
@view
def FACTORY() -> address:
    """
    @notice Factory the zap is associated with
    @return Address of the factory
    """
    return _LEND_FACTORY.address


@external
@view
def admin() -> address:
    """
    @notice Admin allowed to manage the exchange whitelist, delegated to the factory
    @return Address of the admin
    """
    return staticcall _LEND_FACTORY.admin()


@internal
def _set_exchange(_exchange: address, _approved: bool):
    self.is_approved_exchange[_exchange] = _approved
    log ILeverageZap.SetExchange(exchange=_exchange, approved=_approved)


@external
def set_exchange(_exchange: address, _approved: bool):
    """
    @notice Add or remove an exchange (router/pool) from the whitelist of
            targets the zap is allowed to call during leverage callbacks
    @param _exchange Address of the exchange
    @param _approved Whether the exchange is allowed
    """
    assert msg.sender == staticcall _LEND_FACTORY.admin(), "Only admin"
    self._set_exchange(_exchange, _approved)
