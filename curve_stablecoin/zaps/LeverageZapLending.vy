# pragma version 0.4.3
# pragma optimize codesize

"""
@title LlamaLendLeverageZap
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2026 - all rights reserved
@notice Creates leverage on LlamaLend markets via any Aggregator Router. Does calculations for leverage.
"""

from curve_stablecoin.interfaces import IAMM
from curve_stablecoin.interfaces import ILendFactory
from curve_stablecoin.interfaces import IController
from curve_stablecoin import ControllerView
from curve_stablecoin.interfaces import ILeverageZap
from curve_std.interfaces import IERC20
from curve_std import token as tkn
from snekmate.utils import math

implements: ILeverageZap

################################################################
#                          CONSTANTS                           #
################################################################

from curve_stablecoin import constants as c

WAD: constant(uint256) = c.WAD
DEAD_SHARES: constant(uint256) = c.DEAD_SHARES
MAX_TICKS_UINT: constant(uint256) = c.MAX_TICKS_UINT
CALLDATA_MAX_SIZE: constant(uint256) = c.CALLDATA_MAX_SIZE

_LEND_FACTORY: immutable(ILendFactory)

MAX_INIT_EXCHANGES: constant(uint256) = 10

# Whitelist of exchanges (routers/pools) the zap is allowed to `raw_call`
is_approved_exchange: public(HashMap[address, bool])


@deploy
def __init__(_factory: address, _exchanges: DynArray[address, MAX_INIT_EXCHANGES]):
    _LEND_FACTORY = ILendFactory(_factory)

    for exchange: address in _exchanges:
        self._set_exchange(exchange, True)


@internal
@view
def _get_k_effective(_controller: IController, _collateral: uint256, _N: uint256) -> uint256:
    """
    @notice Intermediary method which calculates k_effective defined as x_effective / p_base / y,
            however discounted by loan_discount.
            x_effective is an amount which can be obtained from collateral when liquidating
    @param N Number of bands the deposit is made into
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


@internal
def _callback_deposit(
        _controller: address,
        _user: address,
        _d_debt: uint256,
        _min_recv: uint256,
        _exchange_address: address,
        _exchange_calldata: Bytes[CALLDATA_MAX_SIZE - 5 * 32],
) -> uint256[2]:
    assert self.is_approved_exchange[_exchange_address], "Exchange not approved"

    amm: IAMM = staticcall IController(_controller).amm()
    borrowed_token: IERC20 = IERC20(staticcall amm.coins(0))
    collateral_token: IERC20 = IERC20(staticcall amm.coins(1))

    # Dust cleaning
    tkn.transfer(collateral_token, _user, staticcall collateral_token.balanceOf(self))

    tkn.max_approve(borrowed_token, _exchange_address)
    tkn.max_approve(collateral_token, _controller)

    # Buys collateral token for d_debt
    # The amount to be spent is specified inside the exchange_calldata.
    raw_call(_exchange_address, _exchange_calldata)  # buys leverage_collateral for d_debt

    leverage_collateral: uint256 = staticcall collateral_token.balanceOf(self)
    assert leverage_collateral >= _min_recv, "Slippage"

    # Refund borrowed tokens the exchange didn't spend back to the user (controller requires returned borrowed == 0).
    tkn.transfer(borrowed_token, _user, staticcall borrowed_token.balanceOf(self))

    log ILeverageZap.Deposit(
        user=_user,
        leverage_collateral=leverage_collateral,
        d_debt=_d_debt,
    )

    return [0, leverage_collateral]


@internal
def _callback_repay(
        _controller: address,
        _user: address,
        _min_recv: uint256,
        _exchange_address: address,
        _exchange_calldata: Bytes[CALLDATA_MAX_SIZE - 5 * 32],
) -> uint256[2]:
    assert self.is_approved_exchange[_exchange_address], "Exchange not approved"

    amm: IAMM = staticcall IController(_controller).amm()
    borrowed_token: IERC20 = IERC20(staticcall amm.coins(0))
    collateral_token: IERC20 = IERC20(staticcall amm.coins(1))

    # Dust cleaning
    tkn.transfer(borrowed_token, _user, staticcall borrowed_token.balanceOf(self))

    initial_collateral: uint256 = staticcall collateral_token.balanceOf(self)

    tkn.max_approve(borrowed_token, _controller)
    tkn.max_approve(collateral_token, _controller)
    tkn.max_approve(collateral_token, _exchange_address)

    # Buy borrowed token for collateral from user's position + from user's wallet.
    # The amount to be spent is specified inside the exchange_calldata.
    raw_call(_exchange_address, _exchange_calldata)

    remaining_collateral: uint256 = staticcall collateral_token.balanceOf(self)
    borrowed_from_state_collateral: uint256 = staticcall borrowed_token.balanceOf(self)
    assert borrowed_from_state_collateral >= _min_recv, "Slippage"
    assert remaining_collateral < initial_collateral, "Collateral must decrease"
    state_collateral_used: uint256 = initial_collateral - remaining_collateral

    log ILeverageZap.Repay(
        user=_user,
        state_collateral_used=state_collateral_used,
        borrowed_from_state_collateral=borrowed_from_state_collateral,
    )

    return [borrowed_from_state_collateral, remaining_collateral]


@external
@view
def FACTORY() -> address:
    return _LEND_FACTORY.address


@external
@view
def admin() -> address:
    """
    @notice Admin allowed to manage the exchange whitelist, delegated to the factory
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


@external
@nonreentrant
def callback_deposit(
        _user: address,
        _borrowed: uint256,
        _user_collateral: uint256,
        _d_debt: uint256,
        _calldata: Bytes[CALLDATA_MAX_SIZE],
) -> uint256[2]:
    """
    @notice Callback method which should be called by controller to create leveraged position
    @param _user Address of the user
    @param _borrowed Always 0
    @param _user_collateral The amount of collateral token provided by user (unused)
    @param _d_debt The amount to be borrowed (in addition to what has already been borrowed)
    @param _calldata controller_id + min_recv + exchange_address + exchange_calldata
                    - controller_id is needed to check that msg.sender is the one of our controllers
                    - min_recv - the minimum amount to receive from exchange of _d_debt for collateral tokens
                    - exchange_address - the address of the exchange (e. g. pool, router) to swap borrowed -> collateral
                    - exchange_calldata - the data for the exchange (e. g. pool, router)
    return [0, leverage_collateral]
    """
    controller_id: uint256 = 0
    min_recv: uint256 = 0
    exchange_address: address = empty(address)
    exchange_calldata: Bytes[CALLDATA_MAX_SIZE - 5 * 32] = empty(Bytes[CALLDATA_MAX_SIZE - 5 * 32])
    controller_id, min_recv, exchange_address, exchange_calldata = abi_decode(
        _calldata, (uint256, uint256, address, Bytes[CALLDATA_MAX_SIZE - 5 * 32])
    )

    controller: address = (staticcall _LEND_FACTORY.markets(controller_id)).controller.address
    assert msg.sender == controller, "wrong controller"

    return self._callback_deposit(
        controller,
        _user,
        _d_debt,
        min_recv,
        exchange_address,
        exchange_calldata,
    )


@external
@nonreentrant
def callback_repay(
        _user: address,
        _borrowed: uint256,
        _collateral: uint256,
        _debt: uint256,
        _calldata: Bytes[CALLDATA_MAX_SIZE],
) -> uint256[2]:
    """
    @notice Callback method which should be called by controller to create leveraged position
    @param _user Address of the user
    @param _borrowed The value from user_state
    @param _collateral The value from user_state
    @param _debt The value from user_state
    @param _calldata controller_id + min_recv + exchange_address + exchange_calldata
                    - controller_id is needed to check that msg.sender is the one of our controllers
                    - min_recv - the minimum amount to receive from exchange of state_collateral for borrowed tokens
                    - exchange_address - the address of the exchange (e. g. pool, router) to swap collateral -> borrowed
                    - exchange_calldata - the data for the exchange (e. g. pool, router)
    return [borrowed_from_state_collateral, remaining_collateral]
    """
    controller_id: uint256 = 0
    min_recv: uint256 = 0
    exchange_address: address = empty(address)
    exchange_calldata: Bytes[CALLDATA_MAX_SIZE - 5 * 32] = empty(Bytes[CALLDATA_MAX_SIZE - 5 * 32])
    controller_id, min_recv, exchange_address, exchange_calldata = abi_decode(
        _calldata, (uint256, uint256, address, Bytes[CALLDATA_MAX_SIZE - 5 * 32])
    )

    controller: address = (staticcall _LEND_FACTORY.markets(controller_id)).controller.address
    assert msg.sender == controller, "wrong controller"

    return self._callback_repay(
        controller,
        _user,
        min_recv,
        exchange_address,
        exchange_calldata,
    )
