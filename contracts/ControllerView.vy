# pragma version 0.4.1

from contracts.interfaces import IAMM
from contracts.interfaces import IController
from ethereum.ercs import IERC20Detailed
from contracts import common
from snekmate.utils import math

from ethereum.ercs import IERC20

controller: immutable(IController)

MIN_TICKS_UINT: constant(uint256) = common.MIN_TICKS_UINT
MAX_TICKS_UINT: constant(uint256) = common.MIN_TICKS_UINT
DEAD_SHARES: constant(uint256) = common.DEAD_SHARES
MAX_P_BASE_BANDS: constant(int256) = 5
MAX_SKIP_TICKS: constant(uint256) = 1024

struct Position:
    user: address
    x: uint256
    y: uint256
    debt: uint256
    health: int256


@deploy
def __init__(_controller: IController):
    """
    @notice Initialize the ControllerView contract
    @param _controller Address of the Controller contract
    """
    controller = _controller

@view
@internal
def amm() -> IAMM:
    """
    @notice Get the AMM contract
    @return Address of the AMM contract
    """
    return staticcall controller.amm()

@view
@internal
def debt(_for: address) -> uint256:
    return staticcall controller.debt(_for)

@view
@internal
def liquidation_discount() -> uint256:
    return staticcall controller.liquidation_discount()

@view
@internal
def liquidation_discounts(_for: address) -> uint256:
    return staticcall controller.liquidation_discounts(_for)

@view
@internal
def loan_discount() -> uint256:
    return staticcall controller.loan_discount()

@view
@internal
def calculate_debt_n1(collateral: uint256, debt: uint256, N: uint256, user: address = empty(address)) -> int256:
    return staticcall controller.calculate_debt_n1(collateral, debt, N, user)

@view
@internal
def COLLATERAL_PRECISION() -> uint256:
    collateral_token: IERC20Detailed = IERC20Detailed((staticcall controller.collateral_token()).address)
    return convert(staticcall collateral_token.decimals(), uint256)

@view
@internal
def BORROWED_PRECISION() -> uint256:
    borrowed_token: IERC20Detailed = IERC20Detailed((staticcall controller.borrowed_token()).address)
    return convert(staticcall borrowed_token.decimals(), uint256)

@view
@internal
def BORROWED_TOKEN() -> IERC20:
    return staticcall controller.borrowed_token()

@view
@internal
def n_loans() -> uint256:
    return staticcall controller.n_loans()

@view
@internal
def loans(_for: uint256) -> address:
    return staticcall controller.loans(_for)
    
@view
@internal
def health(_for: address, full: bool = False) -> int256:
    return staticcall controller.health(_for, full)

@view
@internal
def extra_health(_for: address) -> uint256:
    return staticcall controller.extra_health(_for)



@internal
@view
def get_y_effective(collateral: uint256, N: uint256, discount: uint256) -> uint256:
    A: uint256 = staticcall self.amm().A()
    SQRT_BAND_RATIO: uint256 = staticcall controller.sqrt_band_ratio()
    return common.get_y_effective(collateral, N, discount, SQRT_BAND_RATIO, A)

@external
@view
@nonreentrant
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
    ns: int256[2] = staticcall self.amm().read_user_tick_numbers(user)
    debt: int256 = convert(self.debt(user), int256)
    n: uint256 = N
    ld: int256 = 0
    if debt != 0:
        ld = convert(self.liquidation_discounts(user), int256)
        n = convert(unsafe_add(unsafe_sub(ns[1], ns[0]), 1), uint256)
    else:
        ld = convert(self.liquidation_discount(), int256)
        ns[0] = max_value(int256)  # This will trigger a "re-deposit"

    n1: int256 = 0
    collateral: int256 = 0
    x_eff: int256 = 0
    debt += d_debt
    assert debt > 0, "Non-positive debt"

    active_band: int256 = staticcall self.amm().active_band_with_skip()

    if ns[0] > active_band:  # re-deposit
        collateral = convert((staticcall self.amm().get_sum_xy(user))[1], int256) + d_collateral
        n1 = self.calculate_debt_n1(convert(collateral, uint256), convert(debt, uint256), n, user)
        collateral *= convert(self.COLLATERAL_PRECISION(), int256)  # now has 18 decimals
    else:
        n1 = ns[0]
        x_eff = convert(staticcall self.amm().get_x_down(user) * unsafe_mul(10**18, self.BORROWED_PRECISION()), int256)

    debt *= convert(self.BORROWED_PRECISION(), int256)

    p0: int256 = convert(staticcall self.amm().p_oracle_up(n1), int256)
    if ns[0] > active_band:
        x_eff = convert(self.get_y_effective(convert(collateral, uint256), n, 0), int256) * p0

    health: int256 = unsafe_div(x_eff, debt)
    health = health - unsafe_div(health * ld, 10**18) - 10**18

    if full:
        if n1 > active_band:  # We are not in liquidation mode
            p_diff: int256 = max(p0, convert(staticcall self.amm().price_oracle(), int256)) - p0
            if p_diff > 0:
                health += unsafe_div(p_diff * collateral, debt)

    return health


@view
@external
@nonreentrant
def users_to_liquidate(_from: uint256=0, _limit: uint256=0) -> DynArray[Position, 1000]:
    """
    @notice Returns a dynamic array of users who can be "hard-liquidated".
            This method is designed for convenience of liquidation bots.
    @param _from Loan index to start iteration from
    @param _limit Number of loans to look over
    @return Dynamic array with detailed info about positions of users
    """
    n_loans: uint256 = self.n_loans()
    limit: uint256 = _limit
    if _limit == 0:
        limit = n_loans
    ix: uint256 = _from
    out: DynArray[Position, 1000] = []
    for i: uint256 in range(10**6):
        if ix >= n_loans or i == limit:
            break
        user: address = self.loans(ix)
        debt: uint256 = self.debt(user)
        health: int256 = self.health(user, True)
        if health < 0:
            xy: uint256[2] = staticcall self.amm().get_sum_xy(user)
            out.append(Position(
                user=user,
                x=xy[0],
                y=xy[1],
                debt=debt,
                health=health
            ))
        ix += 1
    return out

@view
@external
@nonreentrant
def user_prices(user: address) -> uint256[2]:  # Upper, lower
    """
    @notice Lowest price of the lower band and highest price of the upper band the user has deposit in the AMM
    @param user User address
    @return (upper_price, lower_price)
    """
    assert staticcall self.amm().has_liquidity(user)
    ns: int256[2] = staticcall self.amm().read_user_tick_numbers(user) # ns[1] > ns[0]
    return [staticcall self.amm().p_oracle_up(ns[0]), staticcall self.amm().p_oracle_down(ns[1])]

@view
@external
@nonreentrant
def user_state(user: address) -> uint256[4]:
    """
    @notice Return the user state in one call
    @param user User to return the state for
    @return (collateral, stablecoin, debt, N)
    """
    xy: uint256[2] = staticcall self.amm().get_sum_xy(user)
    ns: int256[2] = staticcall self.amm().read_user_tick_numbers(user) # ns[1] > ns[0]
    return [xy[1], xy[0], self.debt(user), convert(unsafe_add(unsafe_sub(ns[1], ns[0]), 1), uint256)]


# AMM has nonreentrant decorator
@view
@external
def amm_price() -> uint256:
    """
    @notice Current price from the AMM
    """
    return staticcall self.amm().get_p()


@internal
@view
def max_p_base() -> uint256:
    """
    @notice Calculate max base price including skipping bands
    """
    LOGN_A_RATIO: int256 = staticcall controller.logn_a_ratio()
    p_oracle: uint256 = staticcall self.amm().price_oracle()
    # Should be correct unless price changes suddenly by MAX_P_BASE_BANDS+ bands
    n1: int256 = math._wad_ln(convert(staticcall self.amm().get_base_price() * 10**18 // p_oracle, int256))
    if n1 < 0:
        n1 -= LOGN_A_RATIO - 1  # This is to deal with vyper's rounding of negative numbers
    n1 = unsafe_div(n1, LOGN_A_RATIO) + MAX_P_BASE_BANDS
    n_min: int256 = staticcall self.amm().active_band_with_skip()
    n1 = max(n1, n_min + 1)
    p_base: uint256 = staticcall self.amm().p_oracle_up(n1)

    A: uint256 = staticcall self.amm().A()
    Aminus1: uint256 = A - 1
    for i: uint256 in range(MAX_SKIP_TICKS + 1):
        n1 -= 1
        if n1 <= n_min:
            break
        p_base_prev: uint256 = p_base
        p_base = unsafe_div(p_base * A, Aminus1)
        if p_base > p_oracle:
            return p_base_prev

    return p_base


@external
@view
@nonreentrant
def max_borrowable(collateral: uint256, N: uint256, current_debt: uint256 = 0, user: address = empty(address)) -> uint256:
    """
    @notice Calculation of maximum which can be borrowed (details in comments)
    @param collateral Collateral amount against which to borrow
    @param N number of bands to have the deposit into
    @param current_debt Current debt of the user (if any)
    @param user User to calculate the value for (only necessary for nonzero extra_health)
    @return Maximum amount of stablecoin to borrow
    """
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

    y_effective: uint256 = self.get_y_effective(collateral * self.COLLATERAL_PRECISION(), N,
                                                self.loan_discount() + self.extra_health(user))

    x: uint256 = unsafe_sub(max(unsafe_div(y_effective * self.max_p_base(), 10**18), 1), 1)
    x = unsafe_div(x * (10**18 - 10**14), unsafe_mul(10**18, self.BORROWED_PRECISION()))  # Make it a bit smaller
    return min(x, staticcall self.BORROWED_TOKEN().balanceOf(controller.address) + current_debt)  # Cannot borrow beyond the amount of coins Controller has


@external
@view
@nonreentrant
def min_collateral(debt: uint256, N: uint256, user: address = empty(address)) -> uint256:
    """
    @notice Minimal amount of collateral required to support debt
    @param debt The debt to support
    @param N Number of bands to deposit into
    @param user User to calculate the value for (only necessary for nonzero extra_health)
    @return Minimal collateral required
    """
    # Add N**2 to account for precision loss in multiple bands, e.g. N / (y/N) = N**2 / y
    assert N <= MAX_TICKS_UINT and N >= MIN_TICKS_UINT
    return unsafe_div(
        unsafe_div(
            debt * unsafe_mul(10**18, self.BORROWED_PRECISION()) // self.max_p_base() * 10**18 // self.get_y_effective(10**18, N, self.loan_discount() + self.extra_health(user)) + unsafe_add(unsafe_mul(N, unsafe_add(N, 2 * DEAD_SHARES)), unsafe_sub(self.COLLATERAL_PRECISION(), 1)),
            self.COLLATERAL_PRECISION()
        ) * 10**18,
        10**18 - 10**14)