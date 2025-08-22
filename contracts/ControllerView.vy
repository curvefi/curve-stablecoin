# pragma version 0.4.3
# pragma nonreentrancy on
"""
@title Controller View Contract
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2025 - all rights reserved
@notice This contract never requires any direct interaction as the
    main controller contract forwards all relevant calls.
@custom:security security@curve.fi
"""

from contracts.interfaces import IAMM
from contracts.interfaces import IMintController as IController

from ethereum.ercs import IERC20
from ethereum.ercs import IERC20Detailed

from contracts import Controller as core
from contracts import constants as c
from snekmate.utils import math

# https://github.com/vyperlang/vyper/issues/4723
MIN_TICKS_UINT: constant(uint256) = c.MIN_TICKS_UINT
MAX_TICKS_UINT: constant(uint256) = c.MAX_TICKS_UINT
DEAD_SHARES: constant(uint256) = c.DEAD_SHARES
WAD: constant(uint256) = c.WAD
SWAD: constant(int256) = c.SWAD
MAX_P_BASE_BANDS: constant(int256) = 5
MAX_SKIP_TICKS: constant(uint256) = 1024

SQRT_BAND_RATIO: immutable(uint256)
LOGN_A_RATIO: immutable(int256)  # log(A / (A - 1))
A: immutable(uint256)
AMM: immutable(IAMM)
CONTROLLER: immutable(IController)
COLLATERAL_TOKEN: immutable(IERC20)
COLLATERAL_PRECISION: immutable(uint256)
BORROWED_TOKEN: immutable(IERC20)
BORROWED_PRECISION: immutable(uint256)


@deploy
def __init__(
    _controller: IController,
    _sqrt_band_ratio: uint256,
    _logn_a_ratio: int256,
    _amm: IAMM,
    _A: uint256,
    _collateral_token: IERC20,
    _collateral_precision: uint256,
    _borrowed_token: IERC20,
    _borrowed_precision: uint256,
):
    CONTROLLER = _controller
    SQRT_BAND_RATIO = _sqrt_band_ratio
    LOGN_A_RATIO = _logn_a_ratio
    AMM = _amm
    A = _A
    COLLATERAL_TOKEN = _collateral_token
    COLLATERAL_PRECISION = _collateral_precision
    BORROWED_TOKEN = _borrowed_token
    BORROWED_PRECISION = _borrowed_precision


@view
@internal
def _debt(_for: address) -> uint256:
    return staticcall CONTROLLER.debt(_for)


@view
@internal
def _liquidation_discount() -> uint256:
    return staticcall CONTROLLER.liquidation_discount()


@view
@internal
def _liquidation_discounts(_for: address) -> uint256:
    return staticcall CONTROLLER.liquidation_discounts(_for)


@view
@internal
def _loan_discount() -> uint256:
    return staticcall CONTROLLER.loan_discount()


@view
@internal
def _calculate_debt_n1(
    collateral: uint256,
    debt: uint256,
    N: uint256,
    user: address = empty(address),
) -> int256:
    return staticcall CONTROLLER.calculate_debt_n1(collateral, debt, N, user)


@view
@internal
def _n_loans() -> uint256:
    return staticcall CONTROLLER.n_loans()


@view
@internal
def _loans(_for: uint256) -> address:
    return staticcall CONTROLLER.loans(_for)


@view
@internal
def _health(_for: address, full: bool = False) -> int256:
    return staticcall CONTROLLER.health(_for, full)


@view
@internal
def _extra_health(_for: address) -> uint256:
    return staticcall CONTROLLER.extra_health(_for)


@internal
@view
def _get_y_effective(
    collateral: uint256, N: uint256, discount: uint256
) -> uint256:
    return core._get_y_effective(collateral, N, discount, SQRT_BAND_RATIO, A)


@external
@view
def health_calculator(
    user: address,
    d_collateral: int256,
    d_debt: int256,
    full: bool,
    N: uint256 = 0,
) -> int256:
    """
    @notice Natspec for this function is available in its controller contract
    """
    ns: int256[2] = staticcall AMM.read_user_tick_numbers(user)
    debt: int256 = convert(self._debt(user), int256)
    n: uint256 = N
    ld: int256 = 0
    if debt != 0:
        ld = convert(self._liquidation_discounts(user), int256)
        n = convert(unsafe_add(unsafe_sub(ns[1], ns[0]), 1), uint256)
    else:
        ld = convert(self._liquidation_discount(), int256)
        ns[0] = max_value(int256)  # This will trigger a "re-deposit"

    n1: int256 = 0
    collateral: int256 = 0
    x_eff: int256 = 0
    debt += d_debt
    assert debt > 0, "debt<0"

    active_band: int256 = staticcall AMM.active_band_with_skip()

    if ns[0] > active_band:  # re-deposit
        collateral = (
            convert((staticcall AMM.get_sum_xy(user))[1], int256) + d_collateral
        )
        n1 = self._calculate_debt_n1(
            convert(collateral, uint256), convert(debt, uint256), n, user
        )
        collateral *= convert(
            COLLATERAL_PRECISION, int256
        )  # now has 18 decimals
    else:
        n1 = ns[0]
        x_eff = convert(
            staticcall AMM.get_x_down(user)
            * unsafe_mul(WAD, BORROWED_PRECISION),
            int256,
        )

    debt *= convert(BORROWED_PRECISION, int256)

    p0: int256 = convert(staticcall AMM.p_oracle_up(n1), int256)
    if ns[0] > active_band:
        x_eff = (
            convert(
                self._get_y_effective(convert(collateral, uint256), n, 0),
                int256,
            )
            * p0
        )

    health: int256 = unsafe_div(x_eff, debt)
    health = health - unsafe_div(health * ld, SWAD) - SWAD

    if full:
        if n1 > active_band:  # We are not in liquidation mode
            p_diff: int256 = (
                max(p0, convert(staticcall AMM.price_oracle(), int256)) - p0
            )
            if p_diff > 0:
                health += unsafe_div(p_diff * collateral, debt)
    return health


@view
@external
def users_to_liquidate(
    _from: uint256 = 0, _limit: uint256 = 0
) -> DynArray[IController.Position, 1000]:
    """
    @notice Natspec for this function is available in its controller contract
    """
    n_loans: uint256 = self._n_loans()
    limit: uint256 = _limit
    if _limit == 0:
        limit = n_loans
    ix: uint256 = _from
    out: DynArray[IController.Position, 1000] = []
    for i: uint256 in range(10**6):
        if ix >= n_loans or i == limit:
            break
        user: address = self._loans(ix)
        debt: uint256 = self._debt(user)
        health: int256 = self._health(user, True)
        if health < 0:
            xy: uint256[2] = staticcall AMM.get_sum_xy(user)
            out.append(
                IController.Position(
                    user=user, x=xy[0], y=xy[1], debt=debt, health=health
                )
            )
        ix += 1
    return out


@view
@external
def user_prices(user: address) -> uint256[2]:  # Upper, lower
    """
    @notice Natspec for this function is available in its controller contract
    """
    assert staticcall AMM.has_liquidity(user)
    ns: int256[2] = staticcall AMM.read_user_tick_numbers(user)  # ns[1] > ns[0]
    return [
        staticcall AMM.p_oracle_up(ns[0]), staticcall AMM.p_oracle_down(ns[1])
    ]


@view
@external
def user_state(user: address) -> uint256[4]:
    """
    @notice Natspec for this function is available in its controller contract
    """
    xy: uint256[2] = staticcall AMM.get_sum_xy(user)
    ns: int256[2] = staticcall AMM.read_user_tick_numbers(user)  # ns[1] > ns[0]
    return [
        xy[1],
        xy[0],
        self._debt(user),
        convert(unsafe_add(unsafe_sub(ns[1], ns[0]), 1), uint256),
    ]


@internal
@view
def _max_p_base() -> uint256:
    """
    @notice Calculate max base price including skipping bands
    """
    p_oracle: uint256 = staticcall AMM.price_oracle()
    # Should be correct unless price changes suddenly by MAX_P_BASE_BANDS+ bands
    n1: int256 = math._wad_ln(
        convert(staticcall AMM.get_base_price() * WAD // p_oracle, int256)
    )
    if n1 < 0:
        n1 -= (
            LOGN_A_RATIO - 1
        )  # This is to deal with vyper's rounding of negative numbers
    n1 = unsafe_div(n1, LOGN_A_RATIO) + MAX_P_BASE_BANDS
    n_min: int256 = staticcall AMM.active_band_with_skip()
    n1 = max(n1, n_min + 1)
    p_base: uint256 = staticcall AMM.p_oracle_up(n1)

    for i: uint256 in range(MAX_SKIP_TICKS + 1):
        n1 -= 1
        if n1 <= n_min:
            break
        p_base_prev: uint256 = p_base
        p_base = staticcall AMM.p_oracle_up(n1)
        if p_base > p_oracle:
            return p_base_prev
    return p_base


@internal
@view
def _max_borrowable(
    collateral: uint256,
    N: uint256,
    cap: uint256,
    current_debt: uint256,
    user: address,
) -> uint256:

    # Calculation of maximum which can be borrowed.
    # It corresponds to a minimum between the amount corresponding to price_oracle
    # and the one given by the min reachable band.
    #
    # Given by p_oracle (perhaps needs to be multiplied by (A - 1) / A to account for mid-band effects)
    # x_max ~= y_effective * p_oracle
    #
    # Given by band number:
    # if n1 is the lowest empty band in the AMM
    # xmax ~= y_effective * amm.p_oracle_up(n1)
    #
    # When n1 -= 1:
    # p_oracle_up *= A / (A - 1)
    # if N < MIN_TICKS or N > MAX_TICKS:
    assert N >= MIN_TICKS_UINT and N <= MAX_TICKS_UINT

    y_effective: uint256 = self._get_y_effective(
        collateral * COLLATERAL_PRECISION,
        N,
        self._loan_discount() + self._extra_health(user),
    )

    x: uint256 = unsafe_sub(
        max(unsafe_div(y_effective * self._max_p_base(), WAD), 1), 1
    )
    x = unsafe_div(
        x * (WAD - 10**14), unsafe_mul(WAD, BORROWED_PRECISION)
    )  # Make it a bit smaller

    return min(x, cap)


@external
@view
def max_borrowable(
    collateral: uint256,
    N: uint256,
    current_debt: uint256 = 0,
    user: address = empty(address),
) -> uint256:
    """
    @notice Natspec for this function is available in its controller contract
    """
    # Cannot borrow beyond the amount of coins Controller has
    cap: uint256 = (
        staticcall BORROWED_TOKEN.balanceOf(CONTROLLER.address) + current_debt
    )

    return self._max_borrowable(
        collateral,
        N,
        cap,
        current_debt,
        user,
    )


# TODO use pointers to natpsec
@external
@view
def min_collateral(
    debt: uint256, N: uint256, user: address = empty(address)
) -> uint256:
    """
    @notice Natspec for this function is available in its controller contract
    """
    # Add N**2 to account for precision loss in multiple bands, e.g. N / (y/N) = N**2 / y
    assert N <= MAX_TICKS_UINT and N >= MIN_TICKS_UINT
    return unsafe_div(
        unsafe_div(
            debt
            * unsafe_mul(WAD, BORROWED_PRECISION) // self._max_p_base()
            * WAD // self._get_y_effective(
                WAD, N, self._loan_discount() + self._extra_health(user)
            )
            + unsafe_add(
                unsafe_mul(N, unsafe_add(N, 2 * DEAD_SHARES)),
                unsafe_sub(COLLATERAL_PRECISION, 1),
            ),
            COLLATERAL_PRECISION,
        )
        * WAD,
        WAD - 10**14,
    )
