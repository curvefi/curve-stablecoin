# pragma version 0.4.3
# pragma nonreentrancy on
# pragma optimize codesize
"""
@title crvUSD Controller
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2025 - all rights reserved
"""

# TODO restore comments that have been cut to make the bytecode fit

from contracts.interfaces import IAMM
from contracts.interfaces import IMonetaryPolicy
from contracts.interfaces import ILMGauge
from contracts.interfaces import IFactory
from contracts.interfaces import IPriceOracle
from ethereum.ercs import IERC20
from ethereum.ercs import IERC20Detailed

from contracts.interfaces import IMintController as IController
from contracts.interfaces import IControllerView as IView

implements: IController
implements: IView

from snekmate.utils import math

################################################################
#                         IMMUTABLES                           #
################################################################

AMM: immutable(IAMM)
MAX_AMM_FEE: immutable(
    uint256
)  # let's set to MIN_TICKS / A: for example, 4% max fee for A=100
A: immutable(uint256)
LOGN_A_RATIO: immutable(int256)  # log(A / (A - 1))
SQRT_BAND_RATIO: immutable(uint256)

COLLATERAL_TOKEN: immutable(IERC20)
COLLATERAL_PRECISION: immutable(uint256)
BORROWED_TOKEN: immutable(IERC20)
BORROWED_PRECISION: immutable(uint256)
FACTORY: immutable(IFactory)

################################################################
#                          CONSTANTS                           #
################################################################

# TODO add version


from contracts import constants as c

# https://github.com/vyperlang/vyper/issues/4723
WAD: constant(uint256) = c.WAD
SWAD: constant(int256) = c.SWAD
DEAD_SHARES: constant(uint256) = c.DEAD_SHARES
MIN_TICKS_UINT: constant(uint256) = c.MIN_TICKS_UINT

MIN_AMM_FEE: constant(uint256) = 10**6  # 1e-12, still needs to be above 0

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
CALLDATA_MAX_SIZE: constant(uint256) = 10**4

MAX_LOAN_DISCOUNT: constant(uint256) = 5 * 10**17
MIN_LIQUIDATION_DISCOUNT: constant(uint256) = 10**16
MAX_TICKS: constant(int256) = 50
MAX_TICKS_UINT: constant(uint256) = c.MAX_TICKS_UINT
MIN_TICKS: constant(int256) = 4
MAX_SKIP_TICKS: constant(uint256) = 1024
MAX_P_BASE_BANDS: constant(int256) = 5

MAX_RATE: constant(uint256) = 43959106799  # 300% APY
MAX_ORACLE_PRICE_DEVIATION: constant(uint256) = WAD // 2  # 50% deviation

################################################################
#                           STORAGE                            #
################################################################

view_impl: public(address)
_view: IView

liquidation_discount: public(uint256)
loan_discount: public(uint256)
_monetary_policy: IMonetaryPolicy

# https://github.com/vyperlang/vyper/issues/4721
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

# TODO uniform comment style

loans: public(address[2**64 - 1])  # Enumerate existing loans
loan_ix: public(HashMap[address, uint256])  # Position of the loan in the list
n_loans: public(uint256)  # Number of nonzero loans

# cumulative amount of assets ever repaid (including admin fees)
repaid: public(uint256)
# cumulative amount of assets admin fees have been taken from
processed: public(uint256)

# unused for mint controller as it overlaps with debt ceiling
borrow_cap: uint256


@deploy
def __init__(
    _collateral_token: IERC20,
    _borrowed_token: IERC20,
    monetary_policy: IMonetaryPolicy,
    loan_discount: uint256,
    liquidation_discount: uint256,
    _AMM: IAMM,
    view_impl: address,
):

    # In MintController the correct way to limit borrowing
    # is through the debt ceiling.
    # TODO move this to mint controller
    self.borrow_cap = max_value(uint256)

    FACTORY = IFactory(msg.sender)
    AMM = _AMM

    A = staticcall AMM.A()

    LOGN_A_RATIO = math._wad_ln(convert(A * WAD // (A - 1), int256))
    SQRT_BAND_RATIO = isqrt(10**36 * A // (A - 1))

    MAX_AMM_FEE = min(WAD * MIN_TICKS_UINT // A, 10**17)

    COLLATERAL_TOKEN = _collateral_token
    collateral_decimals: uint256 = convert(
        staticcall IERC20Detailed(COLLATERAL_TOKEN.address).decimals(), uint256
    )
    COLLATERAL_PRECISION = pow_mod256(10, 18 - collateral_decimals)

    BORROWED_TOKEN = _borrowed_token
    # TODO refactor this logic to be shared with view
    borrowed_decimals: uint256 = convert(
        staticcall IERC20Detailed(BORROWED_TOKEN.address).decimals(), uint256
    )
    BORROWED_PRECISION = pow_mod256(10, 18 - borrowed_decimals)

    self._monetary_policy = monetary_policy
    self.liquidation_discount = liquidation_discount
    self.loan_discount = loan_discount
    self._total_debt.rate_mul = WAD
    self._set_view(view_impl)


# TODO expose in ll
@external
def set_view(view_impl: address):
    """
    @notice Change the contract used to store view functions.
    @dev This function deploys a new view implementation from a blueprint.
    @param view_impl Address of the new view implementation
    """
    self._check_admin()
    self._set_view(view_impl)


@internal
def _set_view(view_impl: address):
    """
    @notice Set the view implementation
    @param view New view implementation
    """
    self.view_impl = view_impl
    view: address = create_from_blueprint(
        view_impl,
        self,
        SQRT_BAND_RATIO,
        LOGN_A_RATIO,
        AMM,
        A,
        COLLATERAL_TOKEN,
        BORROWED_TOKEN,
    )
    self._view = IView(view)


    # TODO event


@view
@external
def minted() -> uint256:
    return self.processed


@view
@external
def redeemed() -> uint256:
    # TODO add natspec
    return self.repaid


@internal
@view
def _check_admin():
    assert msg.sender == staticcall FACTORY.admin(), "only admin"


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
def _update_total_debt(
    d_debt: uint256, rate_mul: uint256, is_increase: bool
) -> IController.Loan:
    """
    @param d_debt Change in debt amount (unsigned)
    @param rate_mul New rate_mul
    @param is_increase Whether debt increases or decreases
    @notice Update total debt of this controller
    """
    loan: IController.Loan = self._total_debt
    loan.initial_debt = loan.initial_debt * rate_mul // loan.rate_mul
    if is_increase:
        loan.initial_debt += d_debt
        assert loan.initial_debt <= self.borrow_cap, "Borrow cap exceeded"
    else:
        loan.initial_debt = unsafe_sub(max(loan.initial_debt, d_debt), d_debt)
    loan.rate_mul = rate_mul
    self._total_debt = loan

    return loan


@external
def set_price_oracle(price_oracle: IPriceOracle, max_deviation: uint256):
    """
    @notice Set a new price oracle for the AMM
    @param price_oracle New price oracle contract
    @param max_deviation Maximum allowed deviation for the new oracle
        Can be set to max_value(uint256) to skip the check if oracle is broken.
    """
    self._check_admin()
    assert (
        max_deviation <= MAX_ORACLE_PRICE_DEVIATION
        or max_deviation == max_value(uint256)
    )  # dev: invalid max deviation

    # Validate the new oracle has required methods
    extcall price_oracle.price_w()
    new_price: uint256 = staticcall price_oracle.price()

    # Check price deviation isn't too high
    current_oracle: IPriceOracle = staticcall AMM.price_oracle_contract()
    old_price: uint256 = staticcall current_oracle.price()
    if max_deviation != max_value(uint256):
        delta: uint256 = (
            new_price - old_price
            if old_price < new_price
            else old_price - new_price
        )
        max_delta: uint256 = old_price * max_deviation // WAD
        assert delta <= max_delta  # dev: deviation > max

    extcall AMM.set_price_oracle(price_oracle)


@external
@view
def factory() -> IFactory:
    """
    @notice Address of the factory
    """
    return FACTORY


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


@internal
def _save_rate():
    """
    @notice Save current rate
    """
    rate: uint256 = min(extcall self._monetary_policy.rate_write(), MAX_RATE)
    extcall AMM.set_rate(rate)


@external
def save_rate():
    """
    @notice Save current rate
    """
    self._save_rate()


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


# TODO check if needed
# @internal
# @view
# def _get_y_effective(collateral: uint256, N: uint256, discount: uint256) -> uint256:
#     return core._get_y_effective(collateral, N, discount, SQRT_BAND_RATIO, A)

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


@internal
@pure
def _get_y_effective(
    collateral: uint256,
    N: uint256,
    discount: uint256,
    _SQRT_BAND_RATIO: uint256,
    _A: uint256,
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
            WAD,
            min(
                discount
                + unsafe_div(
                    (DEAD_SHARES * WAD),
                    max(unsafe_div(collateral, N), DEAD_SHARES),
                ),
                WAD,
            ),
        ),
        unsafe_mul(_SQRT_BAND_RATIO, N),
    )
    y_effective: uint256 = d_y_effective
    for i: uint256 in range(1, MAX_TICKS_UINT):
        if i == N:
            break
        d_y_effective = unsafe_div(d_y_effective * unsafe_sub(_A, 1), _A)
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
    y_effective: uint256 = self._get_y_effective(
        collateral * COLLATERAL_PRECISION,
        N,
        self.loan_discount + self.extra_health[user],
        SQRT_BAND_RATIO,
        A,
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
        staticcall AMM.p_oracle_up(n1) <= staticcall AMM.price_oracle()
    ), "Debt too high"

    return n1


# TODO delete
@internal
@view
def max_p_base() -> uint256:
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


@external
@view
def max_borrowable(
    collateral: uint256,
    N: uint256,
    current_debt: uint256 = 0,
    user: address = empty(address),
) -> uint256:
    """
    @notice Calculation of maximum which can be borrowed (details in comments)
    @param collateral Collateral amount against which to borrow
    @param N number of bands to have the deposit into
    @param current_debt Current debt of the user (if any)
    @param user User to calculate the value for (only necessary for nonzero extra_health)
    @return Maximum amount of stablecoin to borrow
    """
    return staticcall self._view.max_borrowable(
        collateral, N, current_debt, user
    )


@external
@view
def min_collateral(
    debt: uint256, N: uint256, user: address = empty(address)
) -> uint256:
    return staticcall self._view.min_collateral(debt, N, user)


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
def _check_loan_exists(debt: uint256):
    assert debt > 0, "No loan"


@internal
def execute_callback(
    callbacker: address,
    callback_sig: bytes4,
    user: address,
    stablecoins: uint256,
    collateral: uint256,
    debt: uint256,
    calldata: Bytes[CALLDATA_MAX_SIZE],
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


@internal
def _create_loan(
    collateral: uint256,
    debt: uint256,
    N: uint256,
    _for: address,
    callbacker: address = empty(address),
    calldata: Bytes[CALLDATA_MAX_SIZE] = b"",
) -> uint256:
    if _for != tx.origin:
        # We can create a loan for tx.origin (for example when wrapping ETH with EOA),
        # however need to approve in other cases
        assert self._check_approval(_for)

    more_collateral: uint256 = 0
    if callbacker != empty(address):
        self.transfer(BORROWED_TOKEN, callbacker, debt)
        # If there is any unused debt, callbacker can send it to the user
        more_collateral = self.execute_callback(
            callbacker,
            CALLBACK_DEPOSIT,
            _for,
            0,
            collateral,
            debt,
            calldata,
        ).collateral

    collateral = collateral + more_collateral

    assert self.loan[_for].initial_debt == 0, "Loan already created"
    assert N > MIN_TICKS_UINT - 1, "Need more ticks"
    assert N < MAX_TICKS_UINT + 1, "Need less ticks"

    n1: int256 = self._calculate_debt_n1(collateral, debt, N, _for)
    n2: int256 = n1 + convert(unsafe_sub(N, 1), int256)

    rate_mul: uint256 = staticcall AMM.get_rate_mul()
    self.loan[_for] = IController.Loan(initial_debt=debt, rate_mul=rate_mul)
    liquidation_discount: uint256 = self.liquidation_discount
    self.liquidation_discounts[_for] = liquidation_discount

    n_loans: uint256 = self.n_loans
    self.loans[n_loans] = _for
    self.loan_ix[_for] = n_loans
    self.n_loans = unsafe_add(n_loans, 1)

    self._update_total_debt(debt, rate_mul, True)

    extcall AMM.deposit_range(_for, collateral, n1, n2)

    self.processed += debt
    self._save_rate()

    log IController.UserState(
        user=_for,
        collateral=collateral,
        debt=debt,
        n1=n1,
        n2=n2,
        liquidation_discount=liquidation_discount,
    )
    log IController.Borrow(
        user=_for, collateral_increase=collateral, loan_increase=debt
    )

    self.transferFrom(COLLATERAL_TOKEN, msg.sender, AMM.address, collateral)
    if more_collateral > 0:
        self.transferFrom(
            COLLATERAL_TOKEN, callbacker, AMM.address, more_collateral
        )
    if callbacker == empty(address):
        self.transfer(BORROWED_TOKEN, _for, debt)

    return debt


@external
def create_loan(
    collateral: uint256,
    debt: uint256,
    N: uint256,
    _for: address = msg.sender,
    callbacker: address = empty(address),
    calldata: Bytes[CALLDATA_MAX_SIZE] = b"",
):
    """
    @notice Create loan but pass stablecoin to a callback first so that it can build leverage
    @param collateral Amount of collateral to use
    @param debt Stablecoin debt to take
    @param N Number of bands to deposit into (to do autoliquidation-deliquidation),
           can be from MIN_TICKS to MAX_TICKS
    @param _for Address to create the loan for
    @param callbacker Address of the callback contract
    @param calldata Any data for callbacker
    """
    self._create_loan(collateral, debt, N, _for, callbacker, calldata)


@internal
def _add_collateral_borrow(
    d_collateral: uint256,
    d_debt: uint256,
    _for: address,
    remove_collateral: bool,
    check_rounding: bool,
):
    """
    @notice Internal method to borrow and add or remove collateral
    @param d_collateral Amount of collateral to add
    @param d_debt Amount of debt increase
    @param _for Address to transfer tokens to
    @param remove_collateral Remove collateral instead of adding
    @param check_rounding Check that amount added is no less than the rounding error on the loan
    """
    debt: uint256 = 0
    rate_mul: uint256 = 0
    debt, rate_mul = self._debt(_for)
    self._check_loan_exists(debt)
    debt += d_debt

    xy: uint256[2] = extcall AMM.withdraw(_for, WAD)
    assert xy[0] == 0, "Underwater"
    if remove_collateral:
        xy[1] -= d_collateral
    else:
        xy[1] += d_collateral
        if check_rounding:
            # We need d(x + p*y) > 1 wei. For that, we do an equivalent check (but with x2 for safety)
            # This check is only needed when we add collateral for someone else, so gas is not an issue
            # 2 * 10**(18 - borrow_decimals + collateral_decimals) =
            # = 2 * 10**18 * 10**(18 - borrow_decimals) / 10**(collateral_decimals)
            assert (
                d_collateral * staticcall AMM.price_oracle()
                > 2 * WAD * BORROWED_PRECISION // COLLATERAL_PRECISION
            )
    ns: int256[2] = staticcall AMM.read_user_tick_numbers(_for)
    size: uint256 = convert(unsafe_add(unsafe_sub(ns[1], ns[0]), 1), uint256)
    n1: int256 = self._calculate_debt_n1(xy[1], debt, size, _for)
    n2: int256 = n1 + unsafe_sub(ns[1], ns[0])

    extcall AMM.deposit_range(_for, xy[1], n1, n2)
    self.loan[_for] = IController.Loan(initial_debt=debt, rate_mul=rate_mul)

    liquidation_discount: uint256 = 0
    if _for == msg.sender:
        liquidation_discount = self.liquidation_discount
        self.liquidation_discounts[_for] = liquidation_discount
    else:
        liquidation_discount = self.liquidation_discounts[_for]

    if d_debt != 0:
        self._update_total_debt(d_debt, rate_mul, True)

    if remove_collateral:
        log IController.RemoveCollateral(
            user=_for, collateral_decrease=d_collateral
        )
    else:
        log IController.Borrow(
            user=_for, collateral_increase=d_collateral, loan_increase=d_debt
        )

    log IController.UserState(
        user=_for,
        collateral=xy[1],
        debt=debt,
        n1=n1,
        n2=n2,
        liquidation_discount=liquidation_discount,
    )


@external
def add_collateral(collateral: uint256, _for: address = msg.sender):
    """
    @notice Add extra collateral to avoid bad liqidations
    @param collateral Amount of collateral to add
    @param _for Address to add collateral for
    """
    if collateral == 0:
        return
    self._add_collateral_borrow(collateral, 0, _for, False, _for != msg.sender)
    self.transferFrom(COLLATERAL_TOKEN, msg.sender, AMM.address, collateral)
    self._save_rate()


@external
def remove_collateral(collateral: uint256, _for: address = msg.sender):
    """
    @notice Remove some collateral without repaying the debt
    @param collateral Amount of collateral to remove
    @param _for Address to remove collateral for
    """
    if collateral == 0:
        return
    assert self._check_approval(_for)
    self._add_collateral_borrow(collateral, 0, _for, True, False)
    self.transferFrom(COLLATERAL_TOKEN, AMM.address, _for, collateral)
    self._save_rate()


@external
def borrow_more(
    collateral: uint256,
    debt: uint256,
    _for: address = msg.sender,
    callbacker: address = empty(address),
    calldata: Bytes[CALLDATA_MAX_SIZE] = b"",
):
    """
    @notice Borrow more stablecoins while adding more collateral using a callback (to leverage more)
    @param collateral Amount of collateral to add
    @param debt Amount of stablecoin debt to take
    @param _for Address to borrow for
    @param callbacker Address of the callback contract
    @param calldata Any data for callbacker
    """
    _debt: uint256 = self._borrow_more(
        collateral,
        debt,
        _for,
        callbacker,
        calldata,
    )


@internal
def _borrow_more(
    collateral: uint256,
    debt: uint256,
    _for: address = msg.sender,
    callbacker: address = empty(address),
    calldata: Bytes[CALLDATA_MAX_SIZE] = b"",
) -> uint256:
    if debt == 0:
        return 0
    assert self._check_approval(_for)

    more_collateral: uint256 = 0
    if callbacker != empty(address):
        self.transfer(BORROWED_TOKEN, callbacker, debt)
        # If there is any unused debt, callbacker can send it to the user
        more_collateral = self.execute_callback(
            callbacker,
            CALLBACK_DEPOSIT,
            _for,
            0,
            collateral,
            debt,
            calldata,
        ).collateral

    self._add_collateral_borrow(
        collateral + more_collateral, debt, _for, False, False
    )

    self.transferFrom(COLLATERAL_TOKEN, msg.sender, AMM.address, collateral)
    if more_collateral > 0:
        self.transferFrom(
            COLLATERAL_TOKEN, callbacker, AMM.address, more_collateral
        )
    if callbacker == empty(address):
        self.transfer(BORROWED_TOKEN, _for, debt)

    self.processed += debt
    self._save_rate()

    return debt


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


@external
def repay(
    _d_debt: uint256,
    _for: address = msg.sender,
    max_active_band: int256 = max_value(int256),
    callbacker: address = empty(address),
    calldata: Bytes[CALLDATA_MAX_SIZE] = b"",
):
    """
    @notice Repay debt (partially or fully)
    @param _d_debt The amount of debt to repay from user's wallet. If higher than the current debt - will do full repayment
    @param _for The user to repay the debt for
    @param max_active_band Don't allow active band to be higher than this (to prevent front-running the repay)
    @param callbacker Address of the callback contract
    @param calldata Any data for callbacker
    """
    debt: uint256 = 0
    rate_mul: uint256 = 0
    debt, rate_mul = self._debt(_for)
    self._check_loan_exists(debt)
    approval: bool = self._check_approval(_for)
    xy: uint256[2] = empty(uint256[2])

    cb: IController.CallbackData = empty(IController.CallbackData)
    if callbacker != empty(address):
        assert approval
        xy = extcall AMM.withdraw(_for, WAD)
        self.transferFrom(COLLATERAL_TOKEN, AMM.address, callbacker, xy[1])
        cb = self.execute_callback(
            callbacker, CALLBACK_REPAY, _for, xy[0], xy[1], debt, calldata
        )

    total_stablecoins: uint256 = _d_debt + xy[0] + cb.stablecoins
    assert total_stablecoins > 0  # dev: no coins to repay
    d_debt: uint256 = 0

    # If we have more stablecoins than the debt - full repayment and closing the position
    if total_stablecoins >= debt:
        d_debt = debt
        debt = 0
        if callbacker == empty(address):
            xy = extcall AMM.withdraw(_for, WAD)

        total_stablecoins = 0
        if xy[0] > 0:
            # Only allow full repayment when underwater for the sender to do
            assert approval
            self.transferFrom(BORROWED_TOKEN, AMM.address, self, xy[0])
            total_stablecoins += xy[0]
        if cb.stablecoins > 0:
            self.transferFrom(BORROWED_TOKEN, callbacker, self, cb.stablecoins)
            total_stablecoins += cb.stablecoins
        if total_stablecoins < d_debt:
            _d_debt_effective: uint256 = unsafe_sub(
                d_debt, xy[0] + cb.stablecoins
            )  # <= _d_debt
            self.transferFrom(
                BORROWED_TOKEN, msg.sender, self, _d_debt_effective
            )
            total_stablecoins += _d_debt_effective

        if total_stablecoins > d_debt:
            self.transfer(
                BORROWED_TOKEN, _for, unsafe_sub(total_stablecoins, d_debt)
            )
        # Transfer collateral to _for
        if callbacker == empty(address):
            if xy[1] > 0:
                self.transferFrom(COLLATERAL_TOKEN, AMM.address, _for, xy[1])
        else:
            if cb.collateral > 0:
                self.transferFrom(
                    COLLATERAL_TOKEN, callbacker, _for, cb.collateral
                )
        self._remove_from_list(_for)
        log IController.UserState(
            user=_for, collateral=0, debt=0, n1=0, n2=0, liquidation_discount=0
        )
        log IController.Repay(
            user=_for, collateral_decrease=xy[1], loan_decrease=d_debt
        )
    # Else - partial repayment
    else:
        active_band: int256 = staticcall AMM.active_band_with_skip()
        assert active_band <= max_active_band

        d_debt = total_stablecoins
        debt = unsafe_sub(debt, d_debt)
        ns: int256[2] = staticcall AMM.read_user_tick_numbers(_for)
        size: int256 = unsafe_sub(ns[1], ns[0])
        liquidation_discount: uint256 = self.liquidation_discounts[_for]

        if ns[0] > active_band:
            # Not in soft-liquidation - can use callback and move bands
            new_collateral: uint256 = cb.collateral
            if callbacker == empty(address):
                xy = extcall AMM.withdraw(_for, WAD)
                new_collateral = xy[1]
            ns[0] = self._calculate_debt_n1(
                new_collateral,
                debt,
                convert(unsafe_add(size, 1), uint256),
                _for,
            )
            ns[1] = ns[0] + size
            extcall AMM.deposit_range(_for, new_collateral, ns[0], ns[1])
        else:
            # Underwater - cannot use callback or move bands but can avoid a bad liquidation
            xy = staticcall AMM.get_sum_xy(_for)
            assert callbacker == empty(address)

        if approval:
            # Update liquidation discount only if we are that same user. No rugs
            liquidation_discount = self.liquidation_discount
            self.liquidation_discounts[_for] = liquidation_discount
        else:
            # Doesn't allow non-sender to repay in a way which ends with unhealthy state
            # full = False to make this condition non-manipulatable (and also cheaper on gas)
            assert self._health(_for, debt, False, liquidation_discount) > 0

        if cb.stablecoins > 0:
            self.transferFrom(BORROWED_TOKEN, callbacker, self, cb.stablecoins)
        if _d_debt > 0:
            self.transferFrom(BORROWED_TOKEN, msg.sender, self, _d_debt)

        log IController.UserState(
            user=_for,
            collateral=xy[1],
            debt=debt,
            n1=ns[0],
            n2=ns[1],
            liquidation_discount=liquidation_discount,
        )
        log IController.Repay(
            user=_for, collateral_decrease=0, loan_decrease=d_debt
        )

    self.loan[_for] = IController.Loan(initial_debt=debt, rate_mul=rate_mul)
    self._update_total_debt(d_debt, rate_mul, False)
    # TODO unify naming between debt and d_debt
    self.repaid += d_debt

    self._save_rate()


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
    self._check_loan_exists(debt)
    health: int256 = SWAD - convert(liquidation_discount, int256)
    health = (
        unsafe_div(
            convert(staticcall AMM.get_x_down(user), int256) * health,
            convert(debt, int256),
        )
        - SWAD
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
    return staticcall self._view.health_calculator(
        user, d_collateral, d_debt, full, N
    )


@internal
@pure
def _get_f_remove(frac: uint256, health_limit: uint256) -> uint256:
    # f_remove = ((1 + h / 2) / (1 + h) * (1 - frac) + frac) * frac
    f_remove: uint256 = WAD
    if frac < WAD:
        f_remove = unsafe_div(
            unsafe_mul(
                unsafe_add(WAD, unsafe_div(health_limit, 2)),
                unsafe_sub(WAD, frac),
            ),
            unsafe_add(WAD, health_limit),
        )
        f_remove = unsafe_div(unsafe_mul(unsafe_add(f_remove, frac), frac), WAD)

    return f_remove


@external
def liquidate(
    user: address,
    min_x: uint256,
    _frac: uint256 = 10**18,
    callbacker: address = empty(address),
    calldata: Bytes[10**4] = b"",
):
    """
    @notice Perform a bad liquidation (or self-liquidation) of user if health is not good
    @param min_x Minimal amount of stablecoin to receive (to avoid liquidators being sandwiched)
    @param _frac Fraction to liquidate; 100% = 10**18
    @param callbacker Address of the callback contract
    @param calldata Any data for callbacker
    """
    health_limit: uint256 = 0
    if not self._check_approval(user):
        health_limit = self.liquidation_discounts[user]
    debt: uint256 = 0
    rate_mul: uint256 = 0
    debt, rate_mul = self._debt(user)

    if health_limit != 0:
        assert (
            self._health(user, debt, True, health_limit) < 0
        )  # dev: not enough rekt

    final_debt: uint256 = debt
    # TODO shouldn't clamp max
    frac: uint256 = min(_frac, WAD)
    debt = unsafe_div(debt * frac + (WAD - 1), WAD)
    assert debt > 0
    final_debt = unsafe_sub(final_debt, debt)

    # Withdraw sender's stablecoin and collateral to our contract
    # When frac is set - we withdraw a bit less for the same debt fraction
    # f_remove = ((1 + h/2) / (1 + h) * (1 - frac) + frac) * frac
    # where h is health limit.
    # This is less than full h discount but more than no discount
    xy: uint256[2] = extcall AMM.withdraw(
        user, self._get_f_remove(frac, health_limit)
    )  # [stable, collateral]

    # x increase in same block -> price up -> good
    # x decrease in same block -> price down -> bad
    assert xy[0] >= min_x, "Slippage"

    min_amm_burn: uint256 = min(xy[0], debt)
    self.transferFrom(BORROWED_TOKEN, AMM.address, self, min_amm_burn)

    if debt > xy[0]:
        to_repay: uint256 = unsafe_sub(debt, xy[0])

        if callbacker == empty(address):
            # Withdraw collateral if no callback is present
            self.transferFrom(COLLATERAL_TOKEN, AMM.address, msg.sender, xy[1])
            # Request what's left from user
            self.transferFrom(BORROWED_TOKEN, msg.sender, self, to_repay)

        else:
            # Move collateral to callbacker, call it and remove everything from it back in
            self.transferFrom(COLLATERAL_TOKEN, AMM.address, callbacker, xy[1])
            # Callback
            cb: IController.CallbackData = self.execute_callback(
                callbacker,
                CALLBACK_LIQUIDATE,
                user,
                xy[0],
                xy[1],
                debt,
                calldata,
            )
            assert cb.stablecoins >= to_repay, "no enough proceeds"
            if cb.stablecoins > to_repay:
                self.transferFrom(
                    BORROWED_TOKEN,
                    callbacker,
                    msg.sender,
                    unsafe_sub(cb.stablecoins, to_repay),
                )
            self.transferFrom(BORROWED_TOKEN, callbacker, self, to_repay)
            self.transferFrom(
                COLLATERAL_TOKEN, callbacker, msg.sender, cb.collateral
            )
    else:
        # Withdraw collateral
        self.transferFrom(COLLATERAL_TOKEN, AMM.address, msg.sender, xy[1])
        # Return what's left to user
        if xy[0] > debt:
            self.transferFrom(
                BORROWED_TOKEN,
                AMM.address,
                msg.sender,
                unsafe_sub(xy[0], debt),
            )
    self.loan[user] = IController.Loan(
        initial_debt=final_debt, rate_mul=rate_mul
    )
    log IController.Repay(
        user=user, collateral_decrease=xy[1], loan_decrease=debt
    )
    log IController.Liquidate(
        liquidator=msg.sender,
        user=user,
        collateral_received=xy[1],
        stablecoin_received=xy[0],
        debt=debt,
    )
    if final_debt == 0:
        log IController.UserState(
            user=user, collateral=0, debt=0, n1=0, n2=0, liquidation_discount=0
        )  # Not logging partial removeal b/c we have not enough info
        self._remove_from_list(user)

    self._update_total_debt(debt, rate_mul, False)

    self.repaid += debt
    self._save_rate()


@view
@external
def tokens_to_liquidate(user: address, frac: uint256 = WAD) -> uint256:
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
        WAD,
    )
    debt: uint256 = unsafe_div(self._debt(user)[0] * frac, WAD)

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
    return staticcall self._view.users_to_liquidate(_from, _limit)


@view
@external
@reentrant  # TODO make this consistent
def amm_price() -> uint256:
    """
    @notice Current price from the AMM
    @dev Marked as reentrant because AMM already has a nonreentrant decorator
    """
    return staticcall AMM.get_p()


@view
@external
def user_prices(user: address) -> uint256[2]:  # Upper, lower
    """
    @notice Lowest price of the lower band and highest price of the upper band the user has deposit in the AMM
    @param user User address
    @return (upper_price, lower_price)
    """
    return staticcall self._view.user_prices(user)


@view
@external
def user_state(user: address) -> uint256[4]:
    """
    @notice Return the user state in one call
    @param user User to return the state for
    @return (collateral, stablecoin, debt, N)
    """
    return staticcall self._view.user_state(user)


@external
@reentrant
def set_amm_fee(fee: uint256):
    """
    @notice Set the AMM fee (factory admin only)
    @dev Reentrant because AMM is nonreentrant TODO check this one
    @param fee The fee which should be no higher than MAX_AMM_FEE
    """
    self._check_admin()
    assert fee <= MAX_AMM_FEE and fee >= MIN_AMM_FEE, "Fee"
    extcall AMM.set_fee(fee)


@external
def set_monetary_policy(monetary_policy: IMonetaryPolicy):
    """
    @notice Set monetary policy contract
    @param monetary_policy Address of the monetary policy contract
    """
    self._check_admin()
    self._monetary_policy = monetary_policy
    extcall monetary_policy.rate_write()
    log IController.SetMonetaryPolicy(monetary_policy=monetary_policy)


@external
def set_borrowing_discounts(
    loan_discount: uint256, liquidation_discount: uint256
):
    """
    @notice Set discounts at which we can borrow (defines max LTV) and where bad liquidation starts
    @param loan_discount Discount which defines LTV
    @param liquidation_discount Discount where bad liquidation starts
    """
    self._check_admin()
    assert loan_discount > liquidation_discount
    assert liquidation_discount >= MIN_LIQUIDATION_DISCOUNT
    assert loan_discount <= MAX_LOAN_DISCOUNT
    self.liquidation_discount = liquidation_discount
    self.loan_discount = loan_discount
    log IController.SetBorrowingDiscounts(
        loan_discount=loan_discount, liquidation_discount=liquidation_discount
    )


@external
def set_callback(cb: ILMGauge):
    """
    @notice Set liquidity mining callback
    """
    self._check_admin()
    extcall AMM.set_callback(cb)
    log IController.SetLMCallback(callback=cb)


@external
@view
def admin_fees() -> uint256:
    """
    @notice Calculate the amount of fees obtained from the interest
    """
    processed: uint256 = self.processed
    return unsafe_sub(
        max(self._get_total_debt() + self.repaid, processed), processed
    )


@external
def collect_fees() -> uint256:
    """
    @notice Collect the fees charged as interest.
    """
    # In mint controller, 100% (WAD) fees are
    # collected as admin fees.
    return self._collect_fees(WAD)


@internal
def _collect_fees(admin_fee: uint256) -> uint256:
    if admin_fee == 0:
        return 0

    _to: address = staticcall FACTORY.fee_receiver()

    # Borrowing-based fees
    rate_mul: uint256 = staticcall AMM.get_rate_mul()
    loan: IController.Loan = self._update_total_debt(0, rate_mul, False)
    self._save_rate()

    # Cumulative amount which would have been repaid if all the debt was repaid now
    to_be_repaid: uint256 = loan.initial_debt + self.repaid
    # Cumulative amount which was processed (admin fees have been taken from)
    processed: uint256 = self.processed
    # Difference between to_be_repaid and processed amount is exactly due to interest charged
    if to_be_repaid > processed:
        self.processed = to_be_repaid
        fees: uint256 = (unsafe_sub(to_be_repaid, processed) * admin_fee // WAD)
        self.transfer(BORROWED_TOKEN, _to, fees)
        log IController.CollectFees(amount=fees, new_supply=loan.initial_debt)
        return fees
    else:
        log IController.CollectFees(amount=0, new_supply=loan.initial_debt)
        return 0


@external
def approve(_spender: address, _allow: bool):
    """
    @notice Allow another address to borrow and repay for the user
    @param _spender Address to whitelist for the action
    @param _allow Whether to turn the approval on or off (no amounts)
    """
    self.approval[msg.sender][_spender] = _allow
    log IController.Approval(owner=msg.sender, spender=_spender, allow=_allow)


@internal
@view
def _check_approval(_for: address) -> bool:
    return msg.sender == _for or self.approval[_for][msg.sender]


@external
def set_extra_health(_value: uint256):
    """
    @notice Add a little bit more to loan_discount to start SL with health higher than usual
    @param _value 1e18-based addition to loan_discount
    """
    self.extra_health[msg.sender] = _value
    log IController.SetExtraHealth(user=msg.sender, health=_value)
