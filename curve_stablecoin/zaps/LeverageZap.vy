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
from curve_std.interfaces import IERC20
from curve_std import token as tkn
from snekmate.utils import math


event Deposit:
    user: indexed(address)
    user_collateral: uint256
    user_borrowed: uint256
    user_collateral_from_borrowed: uint256
    debt: uint256
    leverage_collateral: uint256

event Repay:
    user: indexed(address)
    state_collateral_used: uint256
    borrowed_from_state_collateral: uint256
    user_collateral: uint256
    user_collateral_used: uint256
    borrowed_from_user_collateral: uint256
    user_borrowed: uint256

################################################################
#                          CONSTANTS                           #
################################################################

from curve_stablecoin import constants as c

WAD: constant(uint256) = c.WAD
DEAD_SHARES: constant(uint256) = c.DEAD_SHARES
MAX_TICKS_UINT: constant(uint256) = c.MAX_TICKS_UINT
MAX_P_BASE_BANDS: constant(int256) = 5
MAX_SKIP_TICKS: constant(int256) = c.MAX_SKIP_TICKS

FACTORIES: public(DynArray[address, 2])


@deploy
def __init__(_factories: DynArray[address, 2]):
    self.FACTORIES = _factories


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
def callback_deposit(user: address, borrowed: uint256, user_collateral: uint256, d_debt: uint256,
                     callback_args: DynArray[uint256, 10], callback_bytes: Bytes[10**4] = b"") -> uint256[2]:
    """
    @notice Callback method which should be called by controller to create leveraged position
    @param user Address of the user
    @param borrowed Always 0
    @param user_collateral The amount of collateral token provided by user
    @param d_debt The amount to be borrowed (in addition to what has already been borrowed)
    @param callback_args [factory_id, controller_id, user_borrowed]
                         0-1. factory_id, controller_id are needed to check that msg.sender is the one of our controllers
                         2. user_borrowed - the amount of borrowed token provided by user (needs to be exchanged for collateral)
                         3. min_recv - the minimum amount to receive from exchange of (user_borrowed + d_debt) for collateral tokens
    return [0, user_collateral_from_borrowed + leverage_collateral]
    """
    controller: address = (staticcall ILendFactory(self.FACTORIES[callback_args[0]]).markets(callback_args[1])).controller.address
    assert msg.sender == controller, "wrong controller"
    amm: IAMM = staticcall IController(controller).amm()
    borrowed_token: IERC20 = IERC20(staticcall amm.coins(0))
    collateral_token: IERC20 = IERC20(staticcall amm.coins(1))

    router_address: address = empty(address)
    # address x1: 32 bytes x1
    # offset: 32 bytes, length: 32 bytes
    # TOTAL: 96 bytes
    exchange_calldata: Bytes[10 ** 4 - 96 - 16] = empty(Bytes[10 ** 4 - 96 - 16])
    router_address, exchange_calldata = abi_decode(callback_bytes, (address, Bytes[10 ** 4 - 96 - 16]))

    tkn.max_approve(borrowed_token, router_address)
    tkn.max_approve(collateral_token, controller)

    user_borrowed: uint256 = callback_args[2]
    tkn.transfer_from(borrowed_token, user, self, user_borrowed)
    raw_call(router_address, exchange_calldata)  # buys leverage_collateral for user_borrowed + d_debt
    additional_collateral: uint256 = staticcall collateral_token.balanceOf(self)
    assert additional_collateral >= callback_args[3], "Slippage"
    leverage_collateral: uint256 = d_debt * WAD // (d_debt + user_borrowed) * additional_collateral // WAD
    user_collateral_from_borrowed: uint256 = additional_collateral - leverage_collateral

    log Deposit(
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
def callback_repay(user: address, borrowed: uint256, collateral: uint256, debt: uint256,
                   callback_args: DynArray[uint256,10], callback_bytes: Bytes[10 ** 4] = b"") -> uint256[2]:
    """
    @notice Callback method which should be called by controller to create leveraged position
    @param user Address of the user
    @param borrowed The value from user_state
    @param collateral The value from user_state
    @param debt The value from user_state
    @param callback_args [factory_id, controller_id, user_collateral, user_borrowed]
                         0-1. factory_id, controller_id are needed to check that msg.sender is the one of our controllers
                         2. user_collateral - the amount of collateral token provided by user (needs to be exchanged for borrowed)
                         3. user_borrowed - the amount of borrowed token to repay from user's wallet
                         4. min_recv - the minimum amount to receive from exchange of (user_collateral + state_collateral) for borrowed tokens
    return [user_borrowed + borrowed_from_collateral, remaining_collateral]
    """
    controller: address = (staticcall ILendFactory(self.FACTORIES[callback_args[0]]).markets(callback_args[1])).controller.address
    assert msg.sender == controller, "wrong controller"
    amm: IAMM = staticcall IController(controller).amm()
    borrowed_token: IERC20 = IERC20(staticcall amm.coins(0))
    collateral_token: IERC20 = IERC20(staticcall amm.coins(1))

    tkn.max_approve(borrowed_token, controller)
    tkn.max_approve(collateral_token, controller)

    initial_collateral: uint256 = staticcall collateral_token.balanceOf(self)
    user_collateral: uint256 = callback_args[2]
    if callback_bytes != b"":
        router_address: address = empty(address)
        # address x1: 32 bytes x1
        # offset: 32 bytes, length: 32 bytes
        # TOTAL: 96 bytes
        exchange_calldata: Bytes[10 ** 4 - 96 - 16] = empty(Bytes[10 ** 4 - 96 - 16])
        router_address, exchange_calldata = abi_decode(callback_bytes, (address, Bytes[10 ** 4 - 96 - 16]))

        tkn.transfer_from(collateral_token, user, self, user_collateral)
        tkn.max_approve(collateral_token, router_address)

        # Buys borrowed token for collateral from user's position + from user's wallet.
        # The amount to be spent is specified inside callback_bytes.
        raw_call(router_address, exchange_calldata)
    else:
        assert user_collateral == 0
    remaining_collateral: uint256 = staticcall collateral_token.balanceOf(self)
    state_collateral_used: uint256 = 0
    borrowed_from_state_collateral: uint256 = 0
    user_collateral_used: uint256 = user_collateral
    borrowed_from_user_collateral: uint256 = staticcall borrowed_token.balanceOf(self)  # here it's total borrowed_from_collateral
    assert borrowed_from_user_collateral >= callback_args[4], "Slippage"
    if remaining_collateral < initial_collateral:
        state_collateral_used = initial_collateral - remaining_collateral
        borrowed_from_state_collateral = state_collateral_used * WAD // (state_collateral_used + user_collateral_used) * borrowed_from_user_collateral // WAD
        borrowed_from_user_collateral = borrowed_from_user_collateral - borrowed_from_state_collateral
    else:
        user_collateral_used = user_collateral - (remaining_collateral - initial_collateral)

    user_borrowed: uint256 = callback_args[3]
    tkn.transfer_from(borrowed_token, user, self, user_borrowed)

    log Repay(
        user=user,
        state_collateral_used=state_collateral_used,
        borrowed_from_state_collateral=borrowed_from_state_collateral,
        user_collateral=user_collateral,
        user_collateral_used=user_collateral_used,
        borrowed_from_user_collateral=borrowed_from_user_collateral,
        user_borrowed=user_borrowed,
    )

    return [borrowed_from_state_collateral + borrowed_from_user_collateral + user_borrowed, remaining_collateral]
