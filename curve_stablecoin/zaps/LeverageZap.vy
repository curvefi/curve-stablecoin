# pragma version 0.4.3
# pragma optimize codesize

"""
@title LlamaLendLeverageZap
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2025 - all rights reserved
@notice Creates leverage on LlamaLend and crvUSD markets via any Aggregator Router. Does calculations for leverage.
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
MAX_P_BASE_BANDS: constant(int256) = 5
MAX_SKIP_TICKS: constant(int256) = c.MAX_SKIP_TICKS
CALLDATA_MAX_SIZE: constant(uint256) = c.CALLDATA_MAX_SIZE

FACTORY: public(address)


@deploy
def __init__(_factory: address):
    self.FACTORY = _factory


@internal
@view
def _get_k_effective(controller: address, collateral: uint256, N: uint256) -> uint256:
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
    CONTROLLER: IController = IController(controller)
    A: uint256 = staticcall (staticcall CONTROLLER.amm()).A()
    SQRT_BAND_RATIO: uint256 = isqrt(unsafe_div(10 ** 36 * A, unsafe_sub(A, 1)))

    discount: uint256 = staticcall CONTROLLER.loan_discount()
    d_k_effective: uint256 = WAD * unsafe_sub(
        WAD, min(discount + (DEAD_SHARES * WAD) // max(collateral // N, DEAD_SHARES), WAD)
    ) // (SQRT_BAND_RATIO * N)
    k_effective: uint256 = d_k_effective
    for i: uint256 in range(1, MAX_TICKS_UINT):
        if i == N:
            break
        d_k_effective = unsafe_div(d_k_effective * (A - 1), A)
        k_effective = unsafe_add(k_effective, d_k_effective)
    return k_effective


@external
@view
def max_borrowable(controller: address, _user_collateral: uint256, _leverage_collateral: uint256, N: uint256, p_avg: uint256) -> uint256:
    """
    @notice Calculation of maximum which can be borrowed with leverage
    """
    # max_borrowable = collateral / (1 / (k_effective * max_p_base) - 1 / p_avg)
    AMM: IAMM = staticcall IController(controller).amm()
    BORROWED_TOKEN: address = staticcall AMM.coins(0)
    COLLATERAL_TOKEN: address = staticcall AMM.coins(1)
    COLLATERAL_PRECISION: uint256 = pow_mod256(10, convert(18 - staticcall IERC20(COLLATERAL_TOKEN).decimals(), uint256))

    user_collateral: uint256 = _user_collateral * COLLATERAL_PRECISION
    leverage_collateral: uint256 = _leverage_collateral * COLLATERAL_PRECISION
    k_effective: uint256 = self._get_k_effective(controller, user_collateral + leverage_collateral, N)

    A: uint256 = staticcall AMM.A()
    max_p_base: uint256 = ControllerView._max_p_base(AMM, math._wad_ln(convert(A * WAD // (A - 1), int256)))
    max_borrowable: uint256 = user_collateral * WAD // (10**36 // k_effective * WAD // max_p_base - 10**36 // p_avg)

    return min(max_borrowable * 999 // 1000, staticcall IERC20(BORROWED_TOKEN).balanceOf(controller)) # Cannot borrow beyond the amount of coins Controller has


@external
@nonreentrant
def callback_deposit(
        user: address,
        borrowed: uint256,
        user_collateral: uint256,
        d_debt: uint256,
        calldata: Bytes[CALLDATA_MAX_SIZE],
) -> uint256[2]:
    """
    @notice Callback method which should be called by controller to create leveraged position
    @param user Address of the user
    @param borrowed Always 0
    @param user_collateral The amount of collateral token provided by user
    @param d_debt The amount to be borrowed (in addition to what has already been borrowed)
    @param calldata controller_id + user_borrowed + min_recv + exchange_address + exchange_calldata
                    - controller_id is needed to check that msg.sender is the one of our controllers
                    - user_borrowed - the amount of borrowed token provided by user (needs to be exchanged for collateral)
                    - min_recv - the minimum amount to receive from exchange of (user_borrowed + d_debt) for collateral tokens
                    - exchange_address - the address of the exchange (e. g. pool, router) to swap borrowed -> collateral
                    - exchange_calldata - the data for the exchange (e. g. pool, router)
    return [0, user_collateral_from_borrowed + leverage_collateral]
    """

    controller_id: uint256 = 0
    user_borrowed: uint256 = 0
    min_recv: uint256 = 0
    exchange_address: address = empty(address)
    exchange_calldata: Bytes[CALLDATA_MAX_SIZE - 6 * 32] = empty(Bytes[CALLDATA_MAX_SIZE - 6 * 32])
    controller_id, user_borrowed, min_recv, exchange_address, exchange_calldata = abi_decode(
        calldata, (uint256, uint256, uint256, address, Bytes[CALLDATA_MAX_SIZE - 6 * 32])
    )

    controller: address = (staticcall ILendFactory(self.FACTORY).markets(controller_id)).controller.address
    assert msg.sender == controller, "wrong controller"
    amm: IAMM = staticcall IController(controller).amm()
    borrowed_token: IERC20 = IERC20(staticcall amm.coins(0))
    collateral_token: IERC20 = IERC20(staticcall amm.coins(1))

    tkn.max_approve(borrowed_token, exchange_address)
    tkn.max_approve(collateral_token, controller)
    tkn.transfer_from(borrowed_token, user, self, user_borrowed)

    # Buys collateral token for user_borrowed (from wallet) + d_debt
    # The amount to be spent is specified inside the exchange_calldata.
    raw_call(exchange_address, exchange_calldata)  # buys leverage_collateral for user_borrowed + d_debt

    additional_collateral: uint256 = staticcall collateral_token.balanceOf(self)
    assert additional_collateral >= min_recv, "Slippage"
    leverage_collateral: uint256 = d_debt * WAD // (d_debt + user_borrowed) * additional_collateral // WAD
    user_collateral_from_borrowed: uint256 = additional_collateral - leverage_collateral

    log ILeverageZap.Deposit(
        user=user,
        user_collateral=user_collateral,
        user_borrowed=user_borrowed,
        user_collateral_from_borrowed=user_collateral_from_borrowed,
        debt=d_debt,
        leverage_collateral=leverage_collateral,
    )

    return [0, additional_collateral]


@external
@nonreentrant
def callback_repay(
        user: address,
        borrowed: uint256,
        collateral: uint256,
        debt: uint256,
        calldata: Bytes[CALLDATA_MAX_SIZE],
) -> uint256[2]:
    """
    @notice Callback method which should be called by controller to create leveraged position
    @param user Address of the user
    @param borrowed The value from user_state
    @param collateral The value from user_state
    @param debt The value from user_state
    @param calldata controller_id + user_collateral + user_borrowed + min_recv + exchange_address + exchange_calldata
                    - controller_id is needed to check that msg.sender is the one of our controllers
                    - user_collateral - the amount of collateral token provided by user (needs to be exchanged for borrowed)
                    - user_borrowed - the amount of borrowed token to repay from user's wallet
                    - min_recv - the minimum amount to receive from exchange of (user_collateral + state_collateral) for borrowed tokens
                    - exchange_address - the address of the exchange (e. g. pool, router) to swap collateral -> borrowed
                    - exchange_calldata - the data for the exchange (e. g. pool, router)
    return [user_borrowed + borrowed_from_collateral, remaining_collateral]
    """
    controller_id: uint256 = 0
    user_collateral: uint256 = 0
    user_borrowed: uint256 = 0
    min_recv: uint256 = 0
    exchange_address: address = empty(address)
    exchange_calldata: Bytes[CALLDATA_MAX_SIZE - 7 * 32] = empty(Bytes[CALLDATA_MAX_SIZE - 7 * 32])
    controller_id, user_collateral, user_borrowed, min_recv, exchange_address, exchange_calldata = abi_decode(
        calldata, (uint256, uint256, uint256, uint256, address, Bytes[CALLDATA_MAX_SIZE - 7 * 32])
    )

    controller: address = (staticcall ILendFactory(self.FACTORY).markets(controller_id)).controller.address
    assert msg.sender == controller, "wrong controller"
    amm: IAMM = staticcall IController(controller).amm()
    borrowed_token: IERC20 = IERC20(staticcall amm.coins(0))
    collateral_token: IERC20 = IERC20(staticcall amm.coins(1))
    initial_collateral: uint256 = staticcall collateral_token.balanceOf(self)

    tkn.max_approve(borrowed_token, controller)
    tkn.max_approve(collateral_token, controller)
    tkn.max_approve(collateral_token, exchange_address)

    tkn.transfer_from(collateral_token, user, self, user_collateral)

    # Buy borrowed token for collateral from user's position + from user's wallet.
    # The amount to be spent is specified inside the exchange_calldata.
    raw_call(exchange_address, exchange_calldata)

    remaining_collateral: uint256 = staticcall collateral_token.balanceOf(self)
    state_collateral_used: uint256 = 0
    borrowed_from_state_collateral: uint256 = 0
    user_collateral_used: uint256 = user_collateral
    borrowed_from_user_collateral: uint256 = staticcall borrowed_token.balanceOf(self)  # here it's total borrowed_from_collateral
    assert borrowed_from_user_collateral >= min_recv, "Slippage"
    if remaining_collateral < initial_collateral:
        state_collateral_used = initial_collateral - remaining_collateral
        borrowed_from_state_collateral = state_collateral_used * WAD // (state_collateral_used + user_collateral_used) * borrowed_from_user_collateral // WAD
        borrowed_from_user_collateral = borrowed_from_user_collateral - borrowed_from_state_collateral
    else:
        user_collateral_used = user_collateral - (remaining_collateral - initial_collateral)

    tkn.transfer_from(borrowed_token, user, self, user_borrowed)

    log ILeverageZap.Repay(
        user=user,
        state_collateral_used=state_collateral_used,
        borrowed_from_state_collateral=borrowed_from_state_collateral,
        user_collateral=user_collateral,
        user_collateral_used=user_collateral_used,
        borrowed_from_user_collateral=borrowed_from_user_collateral,
        user_borrowed=user_borrowed,
    )

    return [borrowed_from_state_collateral + borrowed_from_user_collateral + user_borrowed, remaining_collateral]
