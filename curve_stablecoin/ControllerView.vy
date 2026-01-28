# pragma version 0.4.3
# pragma nonreentrancy on
"""
@title Controller View Contract
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2025 - all rights reserved
@notice This contract never requires any direct interaction as the
    main controller contract forwards all relevant calls.
@custom:security security@curve.fi
@custom:kill Stateless contract doesn't need to be killed.
"""

from curve_stablecoin.interfaces import IAMM
from curve_stablecoin.interfaces import IController
from curve_std.interfaces import IERC20

from curve_stablecoin import controller as core
from curve_stablecoin import constants as c
from snekmate.utils import math
from curve_std import math as crv_math


# https://github.com/vyperlang/vyper/issues/4723
MIN_TICKS_UINT: constant(uint256) = c.MIN_TICKS_UINT
MAX_TICKS_UINT: constant(uint256) = c.MAX_TICKS_UINT
MIN_TICKS: constant(int256) = c.MIN_TICKS
DEAD_SHARES: constant(uint256) = c.DEAD_SHARES
WAD: constant(uint256) = c.WAD
SWAD: constant(int256) = c.SWAD
MAX_P_BASE_BANDS: constant(int256) = 5
MAX_SKIP_TICKS: constant(uint256) = c.MAX_SKIP_TICKS_UINT

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


@internal
@view
def _debt(_for: address) -> uint256:
    return staticcall CONTROLLER.debt(_for)


@internal
@view
def _liquidation_discount() -> uint256:
    return staticcall CONTROLLER.liquidation_discount()


@internal
@view
def _liquidation_discounts(_for: address) -> uint256:
    return staticcall CONTROLLER.liquidation_discounts(_for)


@internal
@view
def _loan_discount() -> uint256:
    return staticcall CONTROLLER.loan_discount()


@internal
@view
def _extra_health(_for: address) -> uint256:
    return staticcall CONTROLLER.extra_health(_for)


@internal
@view
def _get_y_effective(
    _collateral: uint256, _N: uint256, _discount: uint256
) -> uint256:
    return core._get_y_effective(_collateral, _N, _discount, SQRT_BAND_RATIO, A)


@internal
@view
def _check_approval(_for: address, _caller: address) -> bool:
    return _for == _caller or staticcall CONTROLLER.approval(_for, _caller)


@internal
@view
def _calc_health(_x_eff: uint256, _debt: uint256, _ld: uint256) -> int256:
    health: int256 = SWAD - convert(_ld, int256)
    health = unsafe_div(convert(_x_eff, int256) * health, convert(_debt, int256)) - SWAD

    return health


@internal
@view
def _calc_full_health(_collateral: uint256, _debt: uint256, _N: uint256, _n1: int256, _ld: uint256, _full: bool) -> int256:
    p0: uint256 = staticcall AMM.p_oracle_up(_n1)
    x_eff: uint256 = self._get_y_effective(_collateral * COLLATERAL_PRECISION, _N, 0) * p0 // BORROWED_PRECISION // WAD

    health: int256 = self._calc_health(x_eff, _debt, _ld)

    if _full:
        p_diff: uint256 = crv_math.sub_or_zero(staticcall AMM.price_oracle(), p0)
        if p_diff > 0:
            health += unsafe_div(
                convert(p_diff, int256) * convert(_collateral * COLLATERAL_PRECISION, int256),
                convert(_debt * BORROWED_PRECISION, int256)
            )

    return health


@internal
@view
def _calculate_debt_n1(
    _collateral: uint256,
    _debt: uint256,
    _N: uint256,
    _user: address,
) -> int256:
    """
    @notice Calculate the upper band number for the deposit to sit in to support
            the given debt. Reverts if requested debt is too high.
    @param _collateral Amount of collateral (at its native precision)
    @param _debt Amount of requested debt
    @param _N Number of bands to deposit into
    @return Upper band n1 (n1 <= n2) to deposit into. Signed integer
    """
    assert _debt > 0, "No loan"
    n0: int256 = staticcall AMM.active_band()
    p_base: uint256 = staticcall AMM.p_oracle_up(n0)

    # x_effective = y / N * p_oracle_up(n1) * sqrt((A - 1) / A) * sum_{0..N-1}(((A-1) / A)**k)
    # === d_y_effective * p_oracle_up(n1) * sum(...) === y_effective * p_oracle_up(n1)
    # d_y_effective = y / N / sqrt(A / (A - 1))
    y_effective: uint256 = self._get_y_effective(
        _collateral * COLLATERAL_PRECISION,
        _N,
        self._loan_discount() + self._extra_health(_user),
    )
    # p_oracle_up(n1) = base_price * ((A - 1) / A)**n1

    # We borrow up until min band touches p_oracle,
    # or it touches non-empty bands which cannot be skipped.
    # We calculate required n1 for given (collateral, debt),
    # and if n1 corresponds to price_oracle being too high, or unreachable band
    # - we revert.

    # n1 is band number based on adiabatic trading, e.g. when p_oracle ~ p
    y_effective = unsafe_div(
        y_effective * p_base, _debt * BORROWED_PRECISION + 1
    )  # Now it's a ratio

    # n1 = floor(log(y_effective) / self.logAratio)
    # EVM semantics is not doing floor unlike Python, so we do this
    assert y_effective > 0, "Amount too low"
    n1: int256 = math._wad_ln(convert(y_effective, int256))
    if n1 < 0:
        n1 -= unsafe_sub(
            LOGN_A_RATIO, 1
        )  # This is to deal with vyper's rounding of negative numbers
    n1 = unsafe_div(n1, LOGN_A_RATIO)

    n1 = min(n1, 1024 - convert(_N, int256)) + n0
    if n1 <= n0:
        assert staticcall AMM.can_skip_bands(n1 - 1), "Debt too high"

    assert (
        staticcall AMM.p_oracle_up(n1) <= staticcall AMM.price_oracle()
    ), "Debt too high"

    return n1


@external
@view
def calculate_debt_n1(
    _collateral: uint256,
    _debt: uint256,
    _N: uint256,
    _user: address = empty(address),
) -> int256:
    """
    @notice Natspec for this function is available in its controller contract
    """
    assert _N > MIN_TICKS_UINT - 1, "Need more ticks"
    assert _N < MAX_TICKS_UINT + 1, "Need less ticks"
    return self._calculate_debt_n1(_collateral, _debt, _N, _user)


@external
@view
def create_loan_health_preview(
    _collateral: uint256,
    _debt: uint256,
    _N: uint256,
    _for: address,
    _full: bool,
) -> int256:
    """
    @notice Natspec for this function is available in its controller contract
    """
    assert _debt > 0, "debt==0"
    assert _N > MIN_TICKS_UINT - 1, "Need more ticks"
    assert _N < MAX_TICKS_UINT + 1, "Need less ticks"
    n1: int256 = self._calculate_debt_n1(_collateral, _debt, _N, _for)
    ld: uint256 = self._liquidation_discount()

    return self._calc_full_health(_collateral, _debt, _N, n1, ld, _full)


@internal
@view
def _add_collateral_borrow_health_preview(
        _collateral: uint256,
        _debt: uint256,
        _for: address,
        _full: bool,
        _update_ld: bool,
        _remove: bool,
) -> int256:
    """
    @notice Natspec for this function is available in its controller contract
    """
    debt: uint256 = self._debt(_for)
    ns: int256[2] = staticcall AMM.read_user_tick_numbers(_for)
    N: uint256 = convert(unsafe_add(unsafe_sub(ns[1], ns[0]), 1), uint256)
    xy: uint256[2] = staticcall AMM.get_sum_xy(_for)

    assert debt > 0, "debt==0"
    assert xy[0] == 0, "Underwater"

    collateral: uint256 = xy[1]
    if _remove:
        assert collateral > _collateral, "Can't remove more collateral than user has"
        collateral = unsafe_sub(collateral, _collateral)
    else:
        collateral += _collateral
    debt += _debt

    n1: int256 = self._calculate_debt_n1(collateral, debt, N, _for)

    ld: uint256 = 0
    if _update_ld:
        ld = self._liquidation_discount()
    else:
        ld = self._liquidation_discounts(_for)

    return self._calc_full_health(collateral, debt, N, n1, ld, _full)


@external
@view
def add_collateral_health_preview(
    _collateral: uint256,
    _for: address,
    _caller: address,
    _full: bool,
) -> int256:
    """
    @notice Natspec for this function is available in its controller contract
    """
    return self._add_collateral_borrow_health_preview(
        _collateral, 0, _for, _full, self._check_approval(_for, _caller), False
    )


@external
@view
def remove_collateral_health_preview(
    _collateral: uint256,
    _for: address,
    _full: bool,
) -> int256:
    """
    @notice Natspec for this function is available in its controller contract
    """
    return self._add_collateral_borrow_health_preview(
        _collateral, 0, _for, _full, True, True
    )


@external
@view
def borrow_more_health_preview(
    _collateral: uint256,
    _debt: uint256,
    _for: address,
    _full: bool,
) -> int256:
    """
    @notice Natspec for this function is available in its controller contract
    """
    return self._add_collateral_borrow_health_preview(
        _collateral, _debt, _for, _full, True, False
    )


@external
@view
def repay_health_preview(
    _d_collateral: uint256,
    _d_debt: uint256,
    _for: address,
    _caller: address,
    _shrink: bool,
    _full: bool,
) -> int256:
    """
    @notice Natspec for this function is available in its controller contract
    """
    ns: int256[2] = staticcall AMM.read_user_tick_numbers(_for)
    debt: uint256 = self._debt(_for)
    active_band: int256 = staticcall AMM.active_band_with_skip()

    assert debt > 0, "debt == 0"
    assert debt > _d_debt, "Repay amount is too high"
    debt = unsafe_sub(debt, _d_debt)

    ld: uint256 = 0
    if self._check_approval(_for, _caller):
        ld = self._liquidation_discount()
    else:
        ld = self._liquidation_discounts(_for)

    xy: uint256[2] = staticcall AMM.get_sum_xy(_for)
    assert debt > xy[0], "Repay amount is too high"

    if ns[0] > active_band or _shrink:  # re-deposit
        debt = unsafe_sub(debt, xy[0])

        collateral: uint256 = xy[1]
        assert collateral > _d_collateral, "Can't remove more collateral than user has"
        collateral = unsafe_sub(collateral, _d_collateral)

        if _shrink:
            assert ns[1] >= active_band + MIN_TICKS, "Can't shrink"

        N: uint256 = convert(unsafe_add(unsafe_sub(ns[1], max(ns[0], active_band + 1)), 1), uint256)
        n1: int256 = self._calculate_debt_n1(collateral, debt, N, _for)

        return self._calc_full_health(collateral, debt, N, n1, ld, _full)
    else:
        x_eff: uint256 = staticcall AMM.get_x_down(_for)

        return self._calc_health(x_eff, debt, ld)


@external
@view
def liquidate_health_preview(
    _user: address,
    _caller: address,
    _frac: uint256,
    _full: bool,
) -> int256:
    """
    @notice Natspec for this function is available in its controller contract
    """
    assert _frac < WAD, "frac >= 100%"
    debt: uint256 = self._debt(_user)
    ns: int256[2] = staticcall AMM.read_user_tick_numbers(_user)
    active_band: int256 = staticcall AMM.active_band_with_skip()

    approval: bool = self._check_approval(_user, _caller)
    health_limit: uint256 = 0
    ld: uint256 = 0
    if approval:
        ld = self._liquidation_discount()
    else:
        ld = self._liquidation_discounts(_user)
        health_limit = ld
    f_remove: uint256 = core._get_f_remove(_frac, health_limit)

    x_eff: uint256 = staticcall AMM.get_x_down(_user) * (WAD - f_remove) // WAD
    debt = debt * (WAD - _frac) // WAD
    health: int256 = self._calc_health(x_eff, debt, ld)

    if health > 0 and ns[0] > active_band:
        xy: uint256[2] = staticcall AMM.get_sum_xy(_user)
        collateral: uint256 = xy[1] * (WAD - f_remove) // WAD
        p0: uint256 = staticcall AMM.p_oracle_up(ns[0])

        if _full:
            p_diff: uint256 = crv_math.sub_or_zero(staticcall AMM.price_oracle(), p0)
            if p_diff > 0:
                health += unsafe_div(
                    convert(p_diff, int256) * convert(collateral * COLLATERAL_PRECISION, int256),
                    convert(debt * BORROWED_PRECISION, int256)
                )

    return health


@internal
@view
def users_with_health(
    _controller: IController,
    _from: uint256,
    _limit: uint256,
    _threshold: int256,
    _require_approval: bool,
    _approval_spender: address,
    _full: bool,
) -> DynArray[IController.Position, 1000]:
    """
    Enumerate controller loans and return positions with health < threshold.
    Optionally require controller.approval(user, _approval_spender).
    Returns IController.Position entries (user, x, y, debt, health).
    """
    AMM_: IAMM = staticcall _controller.amm()

    n_loans: uint256 = staticcall _controller.n_loans()
    limit: uint256 = _limit if _limit != 0 else n_loans
    ix: uint256 = _from
    out: DynArray[IController.Position, 1000] = []
    for i: uint256 in range(10**6):
        if ix >= n_loans or i == limit:
            break
        user: address = staticcall _controller.loans(ix)
        h: int256 = staticcall _controller.health(user, _full)
        ok: bool = h < _threshold
        if ok and _require_approval:
            ok = staticcall _controller.approval(user, _approval_spender)
        if ok:
            xy: uint256[2] = staticcall AMM_.get_sum_xy(user)
            debt: uint256 = staticcall _controller.debt(user)
            out.append(
                IController.Position(
                    user=user, x=xy[0], y=xy[1], debt=debt, health=h
                )
            )
        ix += 1
    return out


@external
@view
def users_to_liquidate(
    _from: uint256 = 0, _limit: uint256 = 0
) -> DynArray[IController.Position, 1000]:
    """
    @notice Natspec for this function is available in its controller contract
    """
    return self.users_with_health(
        CONTROLLER,
        _from,
        _limit,
        0,
        False,
        empty(address),
        True,
    )


@external
@view
def user_prices(_user: address) -> uint256[2]:  # Upper, lower
    """
    @notice Natspec for this function is available in its controller contract
    """
    assert staticcall AMM.has_liquidity(_user)
    ns: int256[2] = staticcall AMM.read_user_tick_numbers(_user)  # ns[1] > ns[0]
    return [
        staticcall AMM.p_oracle_up(ns[0]), staticcall AMM.p_oracle_down(ns[1])
    ]


@external
@view
def user_state(_user: address) -> uint256[4]:
    """
    @notice Natspec for this function is available in its controller contract
    """
    xy: uint256[2] = staticcall AMM.get_sum_xy(_user)
    N: uint256 = 0
    if xy[0] > 0 or xy[1] > 0:
        ns: int256[2] = staticcall AMM.read_user_tick_numbers(_user)  # ns[1] > ns[0]
        N = convert(unsafe_add(unsafe_sub(ns[1], ns[0]), 1), uint256)

    return [xy[1], xy[0], self._debt(_user), N]


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

    for _: uint256 in range(MAX_SKIP_TICKS + 1):
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
    _collateral: uint256,
    _N: uint256,
    _cap: uint256,
    _user: address,
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
    assert _N >= MIN_TICKS_UINT and _N <= MAX_TICKS_UINT

    y_effective: uint256 = self._get_y_effective(
        _collateral * COLLATERAL_PRECISION,
        _N,
        self._loan_discount() + self._extra_health(_user),
    )

    x: uint256 = unsafe_sub(
        max(unsafe_div(y_effective * self._max_p_base(), WAD), 1), 1
    )
    x = unsafe_div(
        x * (WAD - 10**14), unsafe_mul(WAD, BORROWED_PRECISION)
    )  # Make it a bit smaller

    return min(x, _cap)


@internal
@view
def _get_cap() -> uint256:
    """
    @notice Cannot borrow beyond the amount of coins Controller has
    """
    return staticcall BORROWED_TOKEN.balanceOf(CONTROLLER.address)


@external
@view
def max_borrowable(
    _collateral: uint256,
    _N: uint256,
    _current_debt: uint256 = 0,
    _user: address = empty(address),
) -> uint256:
    """
    @notice Natspec for this function is available in its controller contract
    """
    return self._max_borrowable(_collateral, _N, self._get_cap() + _current_debt, _user)


@external
@view
def min_collateral(
    _debt: uint256, _N: uint256, _user: address = empty(address)
) -> uint256:
    """
    @notice Natspec for this function is available in its controller contract
    """
    # Add N**2 to account for precision loss in multiple bands, e.g. N / (y/N) = N**2 / y
    assert _N <= MAX_TICKS_UINT and _N >= MIN_TICKS_UINT
    return unsafe_div(
        unsafe_div(
            _debt
            * unsafe_mul(WAD, BORROWED_PRECISION) // self._max_p_base()
            * WAD // self._get_y_effective(
                WAD, _N, self._loan_discount() + self._extra_health(_user)
            )
            + unsafe_add(
                unsafe_mul(_N, unsafe_add(_N, 2 * DEAD_SHARES)),
                unsafe_sub(COLLATERAL_PRECISION, 1),
            ),
            COLLATERAL_PRECISION,
        )
        * WAD,
        WAD - 10**14,
    )


@internal
@view
def _tokens_to_shrink(_user: address, _cap: uint256, _d_collateral: uint256) -> uint256:
    active_band: int256 = staticcall AMM.active_band_with_skip()
    ns: int256[2] = staticcall AMM.read_user_tick_numbers(_user)

    if ns[0] > active_band:
        return 0

    assert ns[1] >= active_band + MIN_TICKS, "Can't shrink"
    size: uint256 = convert(unsafe_sub(ns[1], active_band), uint256)
    xy: uint256[2] = staticcall AMM.get_sum_xy(_user)
    assert xy[1] > _d_collateral, "Can't remove more collateral than user has"
    current_debt: uint256 = self._debt(_user)
    new_debt: uint256 = crv_math.sub_or_zero(current_debt, xy[0])

    # Cannot borrow beyond the amount of coins Controller has
    _cap += new_debt

    max_borrowable: uint256 = self._max_borrowable(xy[1] - _d_collateral, size, _cap, _user)

    return crv_math.sub_or_zero(new_debt, max_borrowable)


@external
@view
def tokens_to_shrink(_user: address, _d_collateral: uint256 = 0) -> uint256:
    """
    @notice Natspec for this function is available in its controller contract
    """
    return self._tokens_to_shrink(_user, self._get_cap(), _d_collateral)
