# @version 0.3.7
"""
@title Health calculator zap for crvUSD controller
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2023 - all rights reserved
"""

interface LLAMMA:
    def A() -> uint256: view
    def read_user_tick_numbers(_for: address) -> int256[2]: view
    def active_band_with_skip() -> int256: view
    def get_sum_xy(user: address) -> uint256[2]: view
    def get_x_down(user: address) -> uint256: view
    def p_oracle_up(n: int256) -> uint256: view
    def price_oracle() -> uint256: view

interface Controller:
    def debt(user: address) -> uint256: view
    def liquidation_discount() -> uint256: view
    def liquidation_discounts(user: address) -> uint256: view
    def calculate_debt_n1(collateral: uint256, debt: uint256, N: uint256) -> int256: view

interface ERC20:
    def decimals() -> uint256: view


AMM: immutable(LLAMMA)
CONTROLLER: immutable(Controller)
COLLATERAL_PRECISION: immutable(uint256)
A: immutable(uint256)
Aminus1: immutable(uint256)
SQRT_BAND_RATIO: immutable(uint256)
MAX_TICKS_UINT: constant(uint256) = 50
DEAD_SHARES: constant(uint256) = 1000


@external
def __init__(
        amm: address,
        controller: address,
        collateral_token: address,
):
    """
    @notice Health calculator zap for crvUSD controller constructor
    @param amm AMM address
    @param controller Controller address
    @param collateral_token Token to use for collateral
    """
    AMM = LLAMMA(amm)
    CONTROLLER = Controller(controller)
    COLLATERAL_PRECISION = pow_mod256(10, 18 - ERC20(collateral_token).decimals())
    _A: uint256 = AMM.A()
    A = _A
    Aminus1 = _A - 1
    SQRT_BAND_RATIO = isqrt(unsafe_div(10**36 * _A, unsafe_sub(_A, 1)))


@internal
@view
def get_y_effective(collateral: uint256, N: uint256, discount: uint256) -> uint256:
    """
    @notice Intermediary method which calculates y_effective defined as x_effective / p_base,
            however discounted by loan_discount.
            x_effective is an amount which can be obtained from collateral when liquidating
    @param collateral Amount of collateral to get the value for
    @param N Number of bands the deposit is made into
    @param discount Loan discount at 1e18 base (e.g. 1e18 == 100%)
    @return y_effective
    """
    # x_effective = sum_{i=0..N-1}(y / N * p(n_{n1+i})) =
    # = y / N * p_oracle_up(n1) * sqrt((A - 1) / A) * sum_{0..N-1}(((A-1) / A)**k)
    # === d_y_effective * p_oracle_up(n1) * sum(...) === y_effective * p_oracle_up(n1)
    # d_y_effective = y / N / sqrt(A / (A - 1))
    # d_y_effective: uint256 = collateral * unsafe_sub(10**18, discount) / (SQRT_BAND_RATIO * N)
    # Make some extra discount to always deposit lower when we have DEAD_SHARES rounding
    d_y_effective: uint256 = collateral * unsafe_sub(
        10**18, min(discount + (DEAD_SHARES * 10**18) / max(collateral / N, DEAD_SHARES), 10**18)
    ) / (SQRT_BAND_RATIO * N)
    y_effective: uint256 = d_y_effective
    for i in range(1, MAX_TICKS_UINT):
        if i == N:
            break
        d_y_effective = unsafe_div(d_y_effective * Aminus1, A)
        y_effective = unsafe_add(y_effective, d_y_effective)
    return y_effective


@external
@view
@nonreentrant('lock')
def health_calculator(user: address, d_collateral: int256, d_debt: int256, full: bool, N: uint256 = 0) -> int256:
    """
    @notice Health predictor in case user changes the debt or collateral
    @param user Address of the user
    @param d_collateral Change in collateral amount (signed)
    @param d_debt Change in debt amount (signed)
    @param full Whether it's a 'full' health or not
    @param N Number of bands in case loan doesn't yet exist
    @return Signed health value
    """
    ns: int256[2] = AMM.read_user_tick_numbers(user)
    debt: int256 = convert(CONTROLLER.debt(user), int256)
    n: uint256 = N
    ld: int256 = 0
    if debt != 0:
        ld = convert(CONTROLLER.liquidation_discounts(user), int256)
        n = convert(unsafe_add(unsafe_sub(ns[1], ns[0]), 1), uint256)
    else:
        ld = convert(CONTROLLER.liquidation_discount(), int256)
        ns[0] = max_value(int256)  # This will trigger a "re-deposit"

    n1: int256 = 0
    collateral: int256 = 0
    x_eff: int256 = 0
    debt += d_debt
    assert debt > 0, "Non-positive debt"

    active_band: int256 = AMM.active_band_with_skip()

    if ns[0] > active_band:  # re-deposit
        collateral = convert(AMM.get_sum_xy(user)[1], int256) + d_collateral
        n1 = CONTROLLER.calculate_debt_n1(convert(collateral, uint256), convert(debt, uint256), n)
        collateral *= convert(COLLATERAL_PRECISION, int256)  # now has 18 decimals
    else:
        n1 = ns[0]
        x_eff = convert(AMM.get_x_down(user) * 10**18, int256)

    p0: int256 = convert(AMM.p_oracle_up(n1), int256)
    if ns[0] > active_band:
        x_eff = convert(self.get_y_effective(convert(collateral, uint256), n, 0), int256) * p0

    health: int256 = unsafe_div(x_eff, debt)
    health = health - unsafe_div(health * ld, 10**18) - 10**18

    if full:
        if n1 > active_band:  # We are not in liquidation mode
            p_diff: int256 = max(p0, convert(AMM.price_oracle(), int256)) - p0
            if p_diff > 0:
                health += unsafe_div(p_diff * collateral, debt)

    return health
