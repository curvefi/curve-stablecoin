# pragma version 0.4.3
# pragma nonreentrancy on

from contracts.interfaces import IAMM
from contracts.interfaces import IMonetaryPolicy
from contracts.interfaces import IController
from ethereum.ercs import IERC20
from ethereum.ercs import IERC20Detailed

from snekmate.utils import math

################################################################
#                         IMMUTABLES                           #
################################################################

AMM: immutable(IAMM)
MAX_AMM_FEE: immutable(
    uint256
)  # let's set to MIN_TICKS / A: for example, 4% max fee for A=100
A: immutable(uint256)
Aminus1: immutable(uint256)
LOGN_A_RATIO: immutable(int256)  # log(A / (A - 1))
SQRT_BAND_RATIO: immutable(uint256)

COLLATERAL_TOKEN: immutable(IERC20)
COLLATERAL_PRECISION: immutable(uint256)
BORROWED_TOKEN: immutable(IERC20)
BORROWED_PRECISION: immutable(uint256)

################################################################
#                          CONSTANTS                           #
################################################################


from contracts import constants as c

WAD: constant(uint256) = c.WAD
DEAD_SHARES: constant(uint256) = c.DEAD_SHARES


MIN_AMM_FEE: constant(uint256) = 10**6  # 1e-12, still needs to be above 0
MIN_TICKS_UINT: constant(uint256) = 4

CALLBACK_DEPOSIT: constant(bytes4) = method_id(
    "callback_deposit(address,uint256,uint256,uint256,bytes)",
    output_type=bytes4,
)
CALLBACK_REPAY: constant(bytes4) = method_id(
    "callback_repay(address,uint256,uint256,uint256,bytes)", output_type=bytes4
)
CALLBACK_LIQUIDATE: constant(bytes4) = method_id(
    "callback_liquidate(address,uint256,uint256,uint256,bytes)",
    output_type=bytes4,
)

MAX_LOAN_DISCOUNT: constant(uint256) = 5 * 10**17
MIN_LIQUIDATION_DISCOUNT: constant(uint256) = (
    10**16
)  # Start liquidating when threshold reached
MAX_TICKS: constant(int256) = 50
MAX_TICKS_UINT: constant(uint256) = c.MAX_TICKS_UINT
MIN_TICKS: constant(int256) = 4
MAX_SKIP_TICKS: constant(uint256) = 1024
MAX_P_BASE_BANDS: constant(int256) = 5

MAX_RATE: constant(uint256) = 43959106799  # 300% APY

################################################################
#                           STORAGE                            #
################################################################

liquidation_discount: public(uint256)
loan_discount: public(uint256)
# TODO make settable
_monetary_policy: IMonetaryPolicy
# TODO can't mark it as public, likely a compiler bug
# TODO make an issue
@external
@view
def monetary_policy() -> IMonetaryPolicy:
    """
    @notice Address of the monetary policy
    """
    return self._monetary_policy


approval: public(HashMap[address, HashMap[address, bool]])
extra_health: public(HashMap[address, uint256])

loan: HashMap[address, IController.Loan]
liquidation_discounts: public(HashMap[address, uint256])
_total_debt: IController.Loan

loans: public(address[2**64 - 1])  # Enumerate existing loans
loan_ix: public(HashMap[address, uint256])  # Position of the loan in the list
n_loans: public(uint256)  # Number of nonzero loans


@deploy
def __init__(
    _AMM: IAMM,
    _collateral_token: IERC20,
    _borrowed_token: IERC20,
    monetary_policy: IMonetaryPolicy,
    loan_discount: uint256,
    liquidation_discount: uint256,
):
    AMM = _AMM

    A = staticcall AMM.A()
    Aminus1 = A - 1

    # TODO check math (removed unsafe)
    LOGN_A_RATIO = math._wad_ln(convert(A * WAD // A - 1, int256))
    # TODO check math
    SQRT_BAND_RATIO = isqrt(10**36 * A // (A - 1))

    MAX_AMM_FEE = min(WAD * MIN_TICKS_UINT // A, 10**17)

    COLLATERAL_TOKEN = _collateral_token
    collateral_decimals: uint256 = convert(
        staticcall IERC20Detailed(COLLATERAL_TOKEN.address).decimals(), uint256
    )
    COLLATERAL_PRECISION = pow_mod256(10, 18 - collateral_decimals)

    BORROWED_TOKEN = _borrowed_token
    borrowed_decimals: uint256 = convert(
        staticcall IERC20Detailed(BORROWED_TOKEN.address).decimals(), uint256
    )
    BORROWED_PRECISION = pow_mod256(10, 18 - borrowed_decimals)

    self._monetary_policy = monetary_policy
    self.liquidation_discount = liquidation_discount
    self.loan_discount = loan_discount
    self._total_debt.rate_mul = 10**18

    # TODO check what this is needed for
    assert extcall BORROWED_TOKEN.approve(
        msg.sender, max_value(uint256), default_return_value=True
    )


################################################################
#                       BUILDING BLOCKS                        #
################################################################


@internal
@view
def _debt(user: address) -> (uint256, uint256):
    """
    @notice Get the value of debt and rate_mul and update the rate_mul counter
    @param user User address
    @return (debt, rate_mul)
    """
    rate_mul: uint256 = staticcall AMM.get_rate_mul()
    loan: IController.Loan = self.loan[user]
    if loan.initial_debt == 0:
        return (0, rate_mul)
    else:
        # Let user repay 1 smallest decimal more so that the system doesn't lose on precision
        # Use ceil div
        debt: uint256 = loan.initial_debt * rate_mul
        if debt % loan.rate_mul > 0:  # if only one loan -> don't have to do it
            if self.n_loans > 1:
                debt += unsafe_sub(loan.rate_mul, 1)
        debt = unsafe_div(
            debt, loan.rate_mul
        )  # loan.rate_mul is nonzero because we just had % successful
        return (debt, rate_mul)


@internal
@view
def _get_total_debt() -> uint256:
    """
    @notice Total debt of this controller
    """
    rate_mul: uint256 = staticcall AMM.get_rate_mul()
    loan: IController.Loan = self._total_debt
    return loan.initial_debt * rate_mul // loan.rate_mul


@internal
@view
def get_y_effective(
    collateral: uint256, N: uint256, discount: uint256
) -> uint256:
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
    d_y_effective: uint256 = unsafe_div(
        collateral
        * unsafe_sub(
            10**18,
            min(
                discount
                + unsafe_div(
                    (DEAD_SHARES * 10**18),
                    max(unsafe_div(collateral, N), DEAD_SHARES),
                ),
                10**18,
            ),
        ),
        unsafe_mul(SQRT_BAND_RATIO, N),
    )
    y_effective: uint256 = d_y_effective
    for i: uint256 in range(1, MAX_TICKS_UINT):
        if i == N:
            break
        d_y_effective = unsafe_div(d_y_effective * Aminus1, A)
        y_effective = unsafe_add(y_effective, d_y_effective)
    return y_effective


@internal
@view
def _calculate_debt_n1(
    collateral: uint256, debt: uint256, N: uint256, user: address
) -> int256:
    """
    @notice Calculate the upper band number for the deposit to sit in to support
            the given debt. Reverts if requested debt is too high.
    @param collateral Amount of collateral (at its native precision)
    @param debt Amount of requested debt
    @param N Number of bands to deposit into
    @return Upper band n1 (n1 <= n2) to deposit into. Signed integer
    """
    assert debt > 0, "No loan"
    n0: int256 = staticcall AMM.active_band()
    p_base: uint256 = staticcall AMM.p_oracle_up(n0)

    # x_effective = y / N * p_oracle_up(n1) * sqrt((A - 1) / A) * sum_{0..N-1}(((A-1) / A)**k)
    # === d_y_effective * p_oracle_up(n1) * sum(...) === y_effective * p_oracle_up(n1)
    # d_y_effective = y / N / sqrt(A / (A - 1))
    y_effective: uint256 = self.get_y_effective(
        collateral * COLLATERAL_PRECISION,
        N,
        self.loan_discount + self.extra_health[user],
    )
    # p_oracle_up(n1) = base_price * ((A - 1) / A)**n1

    # We borrow up until min band touches p_oracle,
    # or it touches non-empty bands which cannot be skipped.
    # We calculate required n1 for given (collateral, debt),
    # and if n1 corresponds to price_oracle being too high, or unreachable band
    # - we revert.

    # n1 is band number based on adiabatic trading, e.g. when p_oracle ~ p
    y_effective = unsafe_div(
        y_effective * p_base, debt * BORROWED_PRECISION + 1
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

    n1 = min(n1, 1024 - convert(N, int256)) + n0
    if n1 <= n0:
        assert staticcall AMM.can_skip_bands(n1 - 1), "Debt too high"

    assert (
        staticcall AMM.p_oracle_up(n1) < staticcall AMM.price_oracle()
    ), "Debt too high"

    return n1


@internal
@view
def max_p_base() -> uint256:
    """
    @notice Calculate max base price including skipping bands
    """
    p_oracle: uint256 = staticcall AMM.price_oracle()
    # Should be correct unless price changes suddenly by MAX_P_BASE_BANDS+ bands
    n1: int256 = math._wad_ln(
        convert(staticcall AMM.get_base_price() * 10**18 // p_oracle, int256)
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
        p_base = unsafe_div(p_base * A, Aminus1)
        if p_base > p_oracle:
            return p_base_prev
    return p_base


@internal
@view
def _check_approval(_for: address) -> bool:
    return msg.sender == _for or self.approval[_for][msg.sender]


@internal
@pure
def _get_f_remove(frac: uint256, health_limit: uint256) -> uint256:
    # f_remove = ((1 + h / 2) / (1 + h) * (1 - frac) + frac) * frac
    f_remove: uint256 = 10**18
    if frac < 10**18:
        f_remove = unsafe_div(
            unsafe_mul(
                unsafe_add(10**18, unsafe_div(health_limit, 2)),
                unsafe_sub(10**18, frac),
            ),
            unsafe_add(10**18, health_limit),
        )
        f_remove = unsafe_div(
            unsafe_mul(unsafe_add(f_remove, frac), frac), 10**18
        )

    return f_remove


@internal
def _remove_from_list(_for: address):
    last_loan_ix: uint256 = self.n_loans - 1
    loan_ix: uint256 = self.loan_ix[_for]
    assert (
        self.loans[loan_ix] == _for
    )  # dev: should never fail but safety first
    self.loan_ix[_for] = 0
    if loan_ix < last_loan_ix:  # Need to replace
        last_loan: address = self.loans[last_loan_ix]
        self.loans[loan_ix] = last_loan
        self.loan_ix[last_loan] = loan_ix
    self.n_loans = last_loan_ix


@internal
def transferFrom(token: IERC20, _from: address, _to: address, amount: uint256):
    if amount > 0:
        assert extcall token.transferFrom(
            _from, _to, amount, default_return_value=True
        )


@internal
def transfer(token: IERC20, _to: address, amount: uint256):
    if amount > 0:
        assert extcall token.transfer(_to, amount, default_return_value=True)


@internal
@view
def _health(
    user: address, debt: uint256, full: bool, liquidation_discount: uint256
) -> int256:
    """
    @notice Returns position health normalized to 1e18 for the user.
            Liquidation starts when < 0, however devaluation of collateral doesn't cause liquidation
    @param user User address to calculate health for
    @param debt The amount of debt to calculate health for
    @param full Whether to take into account the price difference above the highest user's band
    @param liquidation_discount Liquidation discount to use (can be 0)
    @return Health: > 0 = good.
    """
    assert debt > 0, "Loan doesn't exist"
    health: int256 = 10**18 - convert(liquidation_discount, int256)
    health = (
        unsafe_div(
            convert(staticcall AMM.get_x_down(user), int256) * health,
            convert(debt, int256),
        )
        - 10**18
    )

    if full:
        ns0: int256 = (staticcall AMM.read_user_tick_numbers(user))[
            0
        ]  # ns[1] > ns[0]
        if ns0 > staticcall AMM.active_band():  # We are not in liquidation mode
            p: uint256 = staticcall AMM.price_oracle()
            p_up: uint256 = staticcall AMM.p_oracle_up(ns0)
            if p > p_up:
                health += convert(
                    unsafe_div(
                        unsafe_sub(p, p_up)
                        * (staticcall AMM.get_sum_xy(user))[1]
                        * COLLATERAL_PRECISION,
                        debt * BORROWED_PRECISION,
                    ),
                    int256,
                )
    return health


@internal
def _save_rate():
    """
    @notice Save current rate
    """
    rate: uint256 = min(extcall self._monetary_policy.rate_write(), MAX_RATE)
    extcall AMM.set_rate(rate)


@internal
def execute_callback(
    callbacker: address,
    callback_sig: bytes4,
    user: address,
    stablecoins: uint256,
    collateral: uint256,
    debt: uint256,
    calldata: Bytes[10**4],
) -> IController.CallbackData:
    assert callbacker != COLLATERAL_TOKEN.address
    assert callbacker != BORROWED_TOKEN.address

    data: IController.CallbackData = empty(IController.CallbackData)
    data.active_band = staticcall AMM.active_band()
    band_x: uint256 = staticcall AMM.bands_x(data.active_band)
    band_y: uint256 = staticcall AMM.bands_y(data.active_band)

    # Callback
    response: Bytes[64] = raw_call(
        callbacker,
        concat(
            callback_sig,
            abi_encode(user, stablecoins, collateral, debt, calldata),
        ),
        max_outsize=64,
    )
    data.stablecoins = convert(slice(response, 0, 32), uint256)
    data.collateral = convert(slice(response, 32, 32), uint256)

    # Checks after callback
    assert data.active_band == staticcall AMM.active_band()
    assert band_x == staticcall AMM.bands_x(data.active_band)
    assert band_y == staticcall AMM.bands_y(data.active_band)

    return data


################################################################
#                   FIGURE OUT A SECTION NAME                  #
################################################################

@external
def approve(_spender: address, _allow: bool):
    """
    @notice Allow another address to borrow and repay for the user
    @param _spender Address to whitelist for the action
    @param _allow Whether to turn the approval on or off (no amounts)
    """
    self.approval[msg.sender][_spender] = _allow
    log IController.Approval(owner=msg.sender, spender=_spender, allow=_allow)


@external
def set_extra_health(_value: uint256):
    """
    @notice Add a little bit more to loan_discount to start SL with health higher than usual
    @param _value 1e18-based addition to loan_discount
    """
    self.extra_health[msg.sender] = _value
    log IController.SetExtraHealth(user=msg.sender, health=_value)


@external
def save_rate():
    """
    @notice Save current rate
    """
    self._save_rate()


################################################################
#                         VIEW METHODS                         #
################################################################

@external
@view
@reentrant
def amm() -> IAMM:
    """
    @notice Address of the AMM
    """
    return AMM


@external
@view
@reentrant
def collateral_token() -> IERC20:
    """
    @notice Address of the collateral token
    """
    return COLLATERAL_TOKEN


@external
@view
@reentrant
def borrowed_token() -> IERC20:
    """
    @notice Address of the borrowed token
    """
    return BORROWED_TOKEN


@external
@view
def debt(user: address) -> uint256:
    """
    @notice Get the value of debt without changing the state
    @param user User address
    @return Value of debt
    """
    return self._debt(user)[0]


@external
@view
def loan_exists(user: address) -> bool:
    """
    @notice Check whether there is a loan of `user` in existence
    """
    return self.loan[user].initial_debt > 0


@external
@view
@reentrant
def total_debt() -> uint256:
    """
    @notice Total debt of this controller
    @dev Marked as reentrant because used by monetary policy
    # TODO check if @reentrant is actually needed
    """
    return self._get_total_debt()





@external
@view
def min_collateral(
    debt: uint256, N: uint256, user: address = empty(address)
) -> uint256:
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
            debt
            * unsafe_mul(10**18, BORROWED_PRECISION) // self.max_p_base()
            * 10
            ** 18 // self.get_y_effective(
                10**18, N, self.loan_discount + self.extra_health[user]
            )
            + unsafe_add(
                unsafe_mul(N, unsafe_add(N, 2 * DEAD_SHARES)),
                unsafe_sub(COLLATERAL_PRECISION, 1),
            ),
            COLLATERAL_PRECISION,
        )
        * 10**18,
        10**18 - 10**14,
    )


@external
@view
def calculate_debt_n1(
    collateral: uint256,
    debt: uint256,
    N: uint256,
    user: address = empty(address),
) -> int256:
    """
    @notice Calculate the upper band number for the deposit to sit in to support
            the given debt. Reverts if requested debt is too high.
    @param collateral Amount of collateral (at its native precision)
    @param debt Amount of requested debt
    @param N Number of bands to deposit into
    @param user User to calculate n1 for (only necessary for nonzero extra_health)
    @return Upper band n1 (n1 <= n2) to deposit into. Signed integer
    """
    return self._calculate_debt_n1(collateral, debt, N, user)


@view
@external
def user_prices(user: address) -> uint256[2]:  # Upper, lower
    """
    @notice Lowest price of the lower band and highest price of the upper band the user has deposit in the AMM
    @param user User address
    @return (upper_price, lower_price)
    """
    assert staticcall AMM.has_liquidity(user)
    ns: int256[2] = staticcall AMM.read_user_tick_numbers(user)  # ns[1] > ns[0]
    return [
        staticcall AMM.p_oracle_up(ns[0]), staticcall AMM.p_oracle_down(ns[1])
    ]


@view
@external
@reentrant
def amm_price() -> uint256:
    """
    @notice Current price from the AMM
    @dev Marked as reentrant because AMM has a nonreentrant decorator
    # TODO check if @reentrant is actually needed
    """
    return staticcall AMM.get_p()


@view
@external
def user_state(user: address) -> uint256[4]:
    """
    @notice Return the user state in one call
    @param user User to return the state for
    @return (collateral, stablecoin, debt, N)
    """
    xy: uint256[2] = staticcall AMM.get_sum_xy(user)
    ns: int256[2] = staticcall AMM.read_user_tick_numbers(user)  # ns[1] > ns[0]
    return [
        xy[1],
        xy[0],
        self._debt(user)[0],
        convert(unsafe_add(unsafe_sub(ns[1], ns[0]), 1), uint256),
    ]


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
    @notice Health predictor in case user changes the debt or collateral
    @param user Address of the user
    @param d_collateral Change in collateral amount (signed)
    @param d_debt Change in debt amount (signed)
    @param full Whether it's a 'full' health or not
    @param N Number of bands in case loan doesn't yet exist
    @return Signed health value
    """
    ns: int256[2] = staticcall AMM.read_user_tick_numbers(user)
    debt: int256 = convert(self._debt(user)[0], int256)
    n: uint256 = N
    ld: int256 = 0
    if debt != 0:
        ld = convert(self.liquidation_discounts[user], int256)
        n = convert(unsafe_add(unsafe_sub(ns[1], ns[0]), 1), uint256)
    else:
        ld = convert(self.liquidation_discount, int256)
        ns[0] = max_value(int256)  # This will trigger a "re-deposit"

    n1: int256 = 0
    collateral: int256 = 0
    x_eff: int256 = 0
    debt += d_debt
    assert debt > 0, "Non-positive debt"

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
            * unsafe_mul(10**18, BORROWED_PRECISION),
            int256,
        )

    debt *= convert(BORROWED_PRECISION, int256)

    p0: int256 = convert(staticcall AMM.p_oracle_up(n1), int256)
    if ns[0] > active_band:
        x_eff = (
            convert(
                self.get_y_effective(convert(collateral, uint256), n, 0), int256
            )
            * p0
        )

    health: int256 = unsafe_div(x_eff, debt)
    health = health - unsafe_div(health * ld, 10**18) - 10**18

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
def tokens_to_liquidate(user: address, frac: uint256 = 10**18) -> uint256:
    """
    @notice Calculate the amount of stablecoins to have in liquidator's wallet to liquidate a user
    @param user Address of the user to liquidate
    @param frac Fraction to liquidate; 100% = 10**18
    @return The amount of stablecoins needed
    """
    health_limit: uint256 = 0
    if not self._check_approval(user):
        health_limit = self.liquidation_discounts[user]
    stablecoins: uint256 = unsafe_div(
        (staticcall AMM.get_sum_xy(user))[0]
        * self._get_f_remove(frac, health_limit),
        10**18,
    )
    debt: uint256 = unsafe_div(self._debt(user)[0] * frac, 10**18)

    return unsafe_sub(max(debt, stablecoins), stablecoins)


@view
@external
def health(user: address, full: bool = False) -> int256:
    """
    @notice Returns position health normalized to 1e18 for the user.
            Liquidation starts when < 0, however devaluation of collateral doesn't cause liquidation
    """
    return self._health(
        user, self._debt(user)[0], full, self.liquidation_discounts[user]
    )


@view
@external
def users_to_liquidate(
    _from: uint256 = 0, _limit: uint256 = 0
) -> DynArray[IController.Position, 1000]:
    """
    @notice Returns a dynamic array of users who can be "hard-liquidated".
            This method is designed for convenience of liquidation bots.
    @param _from Loan index to start iteration from
    @param _limit Number of loans to look over
    @return Dynamic array with detailed info about positions of users
    """
    n_loans: uint256 = self.n_loans
    limit: uint256 = _limit
    if _limit == 0:
        limit = n_loans
    ix: uint256 = _from
    out: DynArray[IController.Position, 1000] = []
    for i: uint256 in range(10**6):
        if ix >= n_loans or i == limit:
            break
        user: address = self.loans[ix]
        debt: uint256 = self._debt(user)[0]
        health: int256 = self._health(
            user, debt, True, self.liquidation_discounts[user]
        )
        if health < 0:
            xy: uint256[2] = staticcall AMM.get_sum_xy(user)
            out.append(
                IController.Position(
                    user=user, x=xy[0], y=xy[1], debt=debt, health=health
                )
            )
        ix += 1
    return out
