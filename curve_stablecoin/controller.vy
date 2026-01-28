# pragma version 0.4.3
# pragma nonreentrancy on
# pragma optimize codesize

from curve_stablecoin.interfaces import IAMM
from curve_stablecoin.interfaces import IMonetaryPolicy
from curve_stablecoin.interfaces import ILMGauge
from curve_stablecoin.interfaces import IFactory
from curve_stablecoin.interfaces import IPriceOracle
from curve_stablecoin.interfaces import IController
from curve_stablecoin.interfaces import IControllerView as IView
from curve_std.interfaces import IERC20

implements: IController
implements: IView

from curve_std import token as tkn
from curve_std import math as crv_math


from snekmate.utils import math

################################################################
#                         IMMUTABLES                           #
################################################################

AMM: immutable(IAMM)
MAX_AMM_FEE: immutable(uint256)
A: immutable(uint256)
# log(A / (A - 1))
LOGN_A_RATIO: immutable(int256)
SQRT_BAND_RATIO: immutable(uint256)

COLLATERAL_TOKEN: immutable(IERC20)
COLLATERAL_PRECISION: immutable(uint256)
BORROWED_TOKEN: immutable(IERC20)
BORROWED_PRECISION: immutable(uint256)
FACTORY: immutable(IFactory)

################################################################
#                          CONSTANTS                           #
################################################################

from curve_stablecoin import constants as c

version: public(constant(String[5])) = c.__version__

# https://github.com/vyperlang/vyper/issues/4723
WAD: constant(uint256) = c.WAD
SWAD: constant(int256) = c.SWAD
DEAD_SHARES: constant(uint256) = c.DEAD_SHARES
MIN_TICKS_UINT: constant(uint256) = c.MIN_TICKS_UINT
MAX_TICKS_UINT: constant(uint256) = c.MAX_TICKS_UINT
MIN_TICKS: constant(int256) = c.MIN_TICKS
CALLDATA_MAX_SIZE: constant(uint256) = c.CALLDATA_MAX_SIZE


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

MIN_AMM_FEE: constant(uint256) = 10**6  # 1e-12, still needs to be above 0
MAX_RATE: constant(uint256) = 43959106799  # 300% APY
MAX_ORACLE_PRICE_DEVIATION: constant(uint256) = WAD // 2  # 50% deviation

################################################################
#                           STORAGE                            #
################################################################

view_impl: public(address)
_view: IView

liquidation_discount: public(uint256)
loan_discount: public(reentrant(uint256))
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
extra_health: public(reentrant(HashMap[address, uint256]))

loan: HashMap[address, IController.Loan]
liquidation_discounts: public(HashMap[address, uint256])
_total_debt: IController.Loan

# Enumerate existing loans
loans: public(address[2**64 - 1])
# Position of the loan in the list
loan_ix: public(HashMap[address, uint256])
# Number of nonzero loans
n_loans: public(uint256)


# cumulative amount of borrowed assets ever lent
lent: uint256
# cumulative amount of borrowed assets ever repaid
repaid: uint256
# cumulative amount of borrowed assets ever collected as admin fees
collected: uint256


# Admin fees yet to be collected. Goes to zero when collected.
admin_fees: public(uint256)
admin_percentage: public(uint256)

# DANGER DO NOT RELY ON MSG.SENDER IN VIRTUAL METHODS
interface VirtualMethods:
    def _on_debt_increased(_delta: uint256, _total_debt: uint256): nonpayable

implements: VirtualMethods

VIRTUAL: immutable(VirtualMethods)


@deploy
def __init__(
    _collateral_token: IERC20,
    _borrowed_token: IERC20,
    _monetary_policy: IMonetaryPolicy,
    _loan_discount: uint256,
    _liquidation_discount: uint256,
    _amm: IAMM,
    _view_impl: address,
):
    VIRTUAL = VirtualMethods(self)

    FACTORY = IFactory(msg.sender)
    AMM = _amm

    A = staticcall AMM.A()

    LOGN_A_RATIO = math._wad_ln(convert(A * WAD // (A - 1), int256))
    SQRT_BAND_RATIO = isqrt(10**36 * A // (A - 1))

    # let's set to MIN_TICKS / A: for example, 4% max fee for A=100
    MAX_AMM_FEE = min(WAD * MIN_TICKS_UINT // A, 10**17)

    COLLATERAL_TOKEN = _collateral_token
    collateral_decimals: uint256 = convert(staticcall COLLATERAL_TOKEN.decimals(), uint256)
    COLLATERAL_PRECISION = pow_mod256(10, 18 - collateral_decimals)

    BORROWED_TOKEN = _borrowed_token
    borrowed_decimals: uint256 = convert(staticcall BORROWED_TOKEN.decimals(), uint256)
    BORROWED_PRECISION = pow_mod256(10, 18 - borrowed_decimals)

    # This is useless for lending markets, but leaving it doesn't create any harm
    tkn.max_approve(BORROWED_TOKEN, FACTORY.address)


    self._set_borrowing_discounts(_loan_discount, _liquidation_discount)
    self._monetary_policy = _monetary_policy
    self._total_debt.rate_mul = WAD
    self.admin_percentage = WAD
    self._set_view(_view_impl)


@external
def set_view(_view_impl: address):
    """
    @notice Change the contract used to store view functions.
    @dev This function deploys a new view implementation from a blueprint.
    @param _view_impl Address of the new view implementation
    """
    self._check_admin()
    self._set_view(_view_impl)


@internal
def _set_view(_view_impl: address):
    """
    @notice Set the view implementation
    @param _view_impl New view implementation
    """
    assert _view_impl != empty(address) # dev: view implementation is empty address
    self.view_impl = _view_impl
    view: address = create_from_blueprint(
        _view_impl,
        self,
        SQRT_BAND_RATIO,
        LOGN_A_RATIO,
        AMM,
        A,
        COLLATERAL_TOKEN,
        COLLATERAL_PRECISION,
        BORROWED_TOKEN,
        BORROWED_PRECISION,
    )
    self._view = IView(view)

    log IController.SetView(view=view)


@external
@view
def minted() -> uint256:
    return self.lent + self.collected


@external
@view
def redeemed() -> uint256:
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
    _d_debt: uint256, _rate_mul: uint256, _is_increase: bool
) -> IController.Loan:
    """
    @notice Update total debt of this controller
    @dev This method MUST be called strictly BEFORE lent, repaid or collected change
    @param d_debt Change in debt amount (unsigned)
    @param rate_mul New rate_mul
    @param is_increase Whether debt increases or decreases
    """
    loan: IController.Loan = self._total_debt
    loan_with_interest: uint256 = loan.initial_debt * _rate_mul // loan.rate_mul
    accrued_interest: uint256 = loan_with_interest - loan.initial_debt
    accrued_admin_fees: uint256 = accrued_interest * self.admin_percentage // WAD
    self.admin_fees += accrued_admin_fees
    loan.initial_debt = loan_with_interest
    if _is_increase:
        loan.initial_debt += _d_debt
        extcall VIRTUAL._on_debt_increased(_d_debt, loan.initial_debt)
    else:
        loan.initial_debt = crv_math.sub_or_zero(loan.initial_debt, _d_debt)
    loan.rate_mul = _rate_mul
    self._total_debt = loan

    return loan


@external
def set_price_oracle(_price_oracle: IPriceOracle, _max_deviation: uint256):
    """
    @notice Set a new price oracle for the AMM
    @param _price_oracle New price oracle contract
    @param _max_deviation Maximum allowed deviation for the new oracle
        Can be set to max_value(uint256) to skip the check if oracle is broken.
    """
    self._check_admin()
    assert (
        _max_deviation <= MAX_ORACLE_PRICE_DEVIATION
        or _max_deviation == max_value(uint256)
    )  # dev: invalid max deviation

    # Validate the new oracle has required methods
    extcall _price_oracle.price_w()
    new_price: uint256 = staticcall _price_oracle.price()

    # Check price deviation isn't too high
    current_oracle: IPriceOracle = staticcall AMM.price_oracle_contract()
    old_price: uint256 = staticcall current_oracle.price()
    if _max_deviation != max_value(uint256):
        delta: uint256 = (
            new_price - old_price
            if old_price < new_price
            else old_price - new_price
        )
        max_delta: uint256 = old_price * _max_deviation // WAD
        assert delta <= max_delta, "delta>max"

    extcall AMM.set_price_oracle(_price_oracle)


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
def _debt(_user: address) -> (uint256, uint256):
    """
    @notice Get the value of debt and rate_mul and update the rate_mul counter
    @param _user User address
    @return (debt, rate_mul)
    """
    rate_mul: uint256 = staticcall AMM.get_rate_mul()
    loan: IController.Loan = self.loan[_user]
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


@external
@view
def debt(_user: address) -> uint256:
    """
    @notice Get the value of debt without changing the state
    @param _user User address
    @return Value of debt
    """
    return self._debt(_user)[0]


@external
@view
def loan_exists(_user: address) -> bool:
    """
    @notice Check whether there is a loan of `user` in existence
    """
    return self.loan[_user].initial_debt > 0


@external
@view
@reentrant
def total_debt() -> uint256:
    """
    @notice Total debt of this controller
    @dev Marked as reentrant because used by monetary policy
    """
    return self._get_total_debt()


@internal
@pure
def _get_y_effective(
    _collateral: uint256,
    _N: uint256,
    _discount: uint256,
    _SQRT_BAND_RATIO: uint256,
    _A: uint256,
) -> uint256:
    """
    @notice Intermediary method which calculates y_effective defined as x_effective / p_base,
            however discounted by loan_discount.
            x_effective is an amount which can be obtained from collateral when liquidating
    @param _collateral Amount of collateral with 18 decimals to get the value for
    @param _N Number of bands the deposit is made into
    @param _discount Loan discount at 1e18 base (e.g. 1e18 == 100%)
    @return y_effective
    """
    # x_effective = sum_{i=0..N-1}(y / N * p(n_{n1+i})) =
    # = y / N * p_oracle_up(n1) * sqrt((A - 1) / A) * sum_{0..N-1}(((A-1) / A)**k)
    # === d_y_effective * p_oracle_up(n1) * sum(...) === y_effective * p_oracle_up(n1)
    # d_y_effective = y / N / sqrt(A / (A - 1))
    # d_y_effective: uint256 = collateral * unsafe_sub(10**18, discount) / (SQRT_BAND_RATIO * N)
    # Make some extra discount to always deposit lower when we have DEAD_SHARES rounding
    d_y_effective: uint256 = unsafe_div(
        _collateral
        * unsafe_sub(
            WAD,
            min(
                _discount
                + unsafe_div(
                    (DEAD_SHARES * WAD),
                    max(unsafe_div(_collateral, _N), DEAD_SHARES),
                ),
                WAD,
            ),
        ),
        unsafe_mul(_SQRT_BAND_RATIO, _N),
    )
    y_effective: uint256 = d_y_effective
    for i: uint256 in range(1, MAX_TICKS_UINT):
        if i == _N:
            break
        d_y_effective = unsafe_div(d_y_effective * unsafe_sub(_A, 1), _A)
        y_effective = unsafe_add(y_effective, d_y_effective)
    return y_effective


@external
@view
def max_borrowable(
    _collateral: uint256,
    _N: uint256,
    _current_debt: uint256 = 0,
    _user: address = empty(address),
) -> uint256:
    """
    @notice Calculation of maximum which can be borrowed (details in comments)
    @param _collateral Collateral amount against which to borrow
    @param _N number of bands to have the deposit into
    @param _current_debt Current debt of the user (if any)
    @param _user User to calculate the value for (only necessary for nonzero extra_health)
    @return Maximum amount of borrowed asset to borrow
    """
    return staticcall self._view.max_borrowable(
        _collateral, _N, _current_debt, _user
    )


@external
@view
def min_collateral(
    _debt: uint256, _N: uint256, _user: address = empty(address)
) -> uint256:
    """
    @notice Calculation of minimum collaterl amount required for given debt amount
    @param _debt The amount of debt for which calculation should be done
    @param _N number of bands to have the deposit into
    @param _user User to calculate the value for (only necessary for nonzero extra_health)
    @return Minimum amount of collateral asset to provide
    """
    return staticcall self._view.min_collateral(_debt, _N, _user)


@external
@view
def calculate_debt_n1(
    _collateral: uint256,
    _debt: uint256,
    _N: uint256,
    _user: address = empty(address),
) -> int256:
    """
    @notice Calculate the upper band number for the deposit to sit in to support
            the given debt. Reverts if requested debt is too high.
    @param _collateral Amount of collateral (at its native precision)
    @param _debt Amount of requested debt
    @param _N Number of bands to deposit into
    @param _user User to calculate n1 for (only necessary for nonzero extra_health)
    @return Upper band n1 (n1 <= n2) to deposit into. Signed integer
    """
    return staticcall self._view.calculate_debt_n1(_collateral, _debt, _N, _user)


@internal
@view
def _check_loan_exists(_debt: uint256):
    # Abstraction to save bytecode on error messages
    assert _debt > 0, "Loan doesn't exist"


@internal
def execute_callback(
    _callbacker: address,
    _callback_sig: bytes4,
    _user: address,
    _borrowed: uint256,
    _collateral: uint256,
    _debt: uint256,
    _calldata: Bytes[CALLDATA_MAX_SIZE],
) -> IController.CallbackData:
    assert _callbacker != COLLATERAL_TOKEN.address
    assert _callbacker != BORROWED_TOKEN.address

    data: IController.CallbackData = empty(IController.CallbackData)
    data.active_band = staticcall AMM.active_band()
    band_x: uint256 = staticcall AMM.bands_x(data.active_band)
    band_y: uint256 = staticcall AMM.bands_y(data.active_band)

    # Callback
    response: Bytes[64] = raw_call(
        _callbacker,
        concat(
            _callback_sig,
            abi_encode(_user, _borrowed, _collateral, _debt, _calldata),
        ),
        max_outsize=64,
    )
    data.borrowed = convert(slice(response, 0, 32), uint256)
    data.collateral = convert(slice(response, 32, 32), uint256)

    # Checks after callback
    assert data.active_band == staticcall AMM.active_band()
    assert band_x == staticcall AMM.bands_x(data.active_band)
    assert band_y == staticcall AMM.bands_y(data.active_band)

    return data


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
    @notice Calculates health after calling create_loan with the same params
    @param _collateral Amount of collateral to use (from wallet + callback).
           Note: the collateral amount coming from the callback should be included.
    @param _debt Borrowed asset debt to take
    @param _N Number of bands to deposit into (to do autoliquidation-deliquidation),
           can be from MIN_TICKS to MAX_TICKS
    @param _full Whether it's a 'full' health or not
    @return Signed health value
    """
    return staticcall self._view.create_loan_health_preview(
        _collateral, _debt, _N, _for, _full
    )


@external
def create_loan(
    _collateral: uint256,
    _debt: uint256,
    _N: uint256,
    _for: address = msg.sender,
    _callbacker: address = empty(address),
    _calldata: Bytes[CALLDATA_MAX_SIZE] = b"",
):
    """
    @notice Create loan but pass borrowed tokens to a callback first so that it can build leverage
    @param _collateral Amount of collateral to use
    @param _debt Borrowed asset debt to take
    @param _N Number of bands to deposit into (to do autoliquidation-deliquidation),
           can be from MIN_TICKS to MAX_TICKS
    @param _for Address to create the loan for
    @param _callbacker Address of the callback contract
    @param _calldata Any data for callbacker
    """
    assert self._check_approval(_for)

    more_collateral: uint256 = 0
    if _callbacker != empty(address):
        tkn.transfer(BORROWED_TOKEN, _callbacker, _debt)
        # If there is any unused debt, callbacker can send it to the user
        more_collateral = self.execute_callback(
            _callbacker,
            CALLBACK_DEPOSIT,
            _for,
            0,
            _collateral,
            _debt,
            _calldata,
        ).collateral

    total_collateral: uint256 = _collateral + more_collateral

    assert self.loan[_for].initial_debt == 0, "Loan already created"
    assert _N > MIN_TICKS_UINT - 1, "Need more ticks"
    assert _N < MAX_TICKS_UINT + 1, "Need less ticks"

    n1: int256 = staticcall self._view.calculate_debt_n1(total_collateral, _debt, _N, _for)
    n2: int256 = n1 + convert(unsafe_sub(_N, 1), int256)

    rate_mul: uint256 = staticcall AMM.get_rate_mul()
    self.loan[_for] = IController.Loan(initial_debt=_debt, rate_mul=rate_mul)
    liquidation_discount: uint256 = self.liquidation_discount
    self.liquidation_discounts[_for] = liquidation_discount

    n_loans: uint256 = self.n_loans
    self.loans[n_loans] = _for
    self.loan_ix[_for] = n_loans
    self.n_loans = unsafe_add(n_loans, 1)

    extcall AMM.deposit_range(_for, total_collateral, n1, n2)

    tkn.transfer_from(COLLATERAL_TOKEN, msg.sender, AMM.address, _collateral)
    tkn.transfer_from(COLLATERAL_TOKEN, _callbacker, AMM.address, more_collateral)
    if _callbacker == empty(address):
        tkn.transfer(BORROWED_TOKEN, _for, _debt)

    self._update_total_debt(_debt, rate_mul, True)
    self.lent += _debt
    self._save_rate()

    log IController.UserState(
        user=_for,
        collateral=total_collateral,
        borrowed=0,
        debt=_debt,
        n1=n1,
        n2=n2,
        liquidation_discount=liquidation_discount,
    )
    log IController.Borrow(
        user=_for, collateral_increase=total_collateral, loan_increase=_debt
    )


@internal
def _update_user_liquidation_discount(_for: address, _approval: bool, _new_debt: uint256) -> uint256:
    # Update liquidation discount only if it's the same or approved user. No rugs
    liquidation_discount: uint256 = 0
    if _approval:
        liquidation_discount = self.liquidation_discount
        self.liquidation_discounts[_for] = liquidation_discount
    else:
        liquidation_discount = self.liquidation_discounts[_for]

    # Doesn't allow non-approved callers to end with unhealthy state, except unhealthy user liquidation case (new_debt == 0)
    # full = False to make this condition non-manipulatable (and also cheaper on gas)
    if not _approval and _new_debt > 0:
        assert self._health(_for, _new_debt, False, liquidation_discount) > 0, "The action ends with unhealthy state"

    return liquidation_discount


@internal
def _add_collateral_borrow(
    _d_collateral: uint256,
    _d_debt: uint256,
    _for: address,
    _remove_collateral: bool,
    _check_rounding: bool,
) -> uint256:
    """
    @notice Internal method to borrow and add or remove collateral
    @param _d_collateral Amount of collateral to add
    @param _d_debt Amount of debt increase
    @param _for Address to transfer tokens to
    @param _remove_collateral Remove collateral instead of adding
    @param check_rounding Check that amount added is no less than the rounding error on the loan
    """
    debt: uint256 = 0
    rate_mul: uint256 = 0
    debt, rate_mul = self._debt(_for)
    self._check_loan_exists(debt)
    debt += _d_debt

    xy: uint256[2] = extcall AMM.withdraw(_for, WAD)
    assert xy[0] == 0, "Underwater"
    if _remove_collateral:
        xy[1] -= _d_collateral
    else:
        xy[1] += _d_collateral
        if _check_rounding:
            # We need d(x + p*y) > 1 wei. For that, we do an equivalent check (but with x2 for safety)
            # This check is only needed when we add collateral for someone else, so gas is not an issue
            # 2 * 10**(18 - borrow_decimals + collateral_decimals) =
            # = 2 * 10**18 * 10**(18 - borrow_decimals) / 10**(18 - collateral_decimals)
            assert (
                _d_collateral * staticcall AMM.price_oracle()
                > 2 * WAD * BORROWED_PRECISION // COLLATERAL_PRECISION
            )
    ns: int256[2] = staticcall AMM.read_user_tick_numbers(_for)
    size: uint256 = convert(unsafe_add(unsafe_sub(ns[1], ns[0]), 1), uint256)
    n1: int256 = staticcall self._view.calculate_debt_n1(xy[1], debt, size, _for)
    n2: int256 = n1 + unsafe_sub(ns[1], ns[0])

    extcall AMM.deposit_range(_for, xy[1], n1, n2)
    self.loan[_for] = IController.Loan(initial_debt=debt, rate_mul=rate_mul)

    liquidation_discount: uint256 = self._update_user_liquidation_discount(_for, self._check_approval(_for), debt)

    if _remove_collateral:
        log IController.RemoveCollateral(
            user=_for, collateral_decrease=_d_collateral
        )
    else:
        log IController.Borrow(
            user=_for, collateral_increase=_d_collateral, loan_increase=_d_debt
        )

    log IController.UserState(
        user=_for,
        collateral=xy[1],
        borrowed=0,
        debt=debt,
        n1=n1,
        n2=n2,
        liquidation_discount=liquidation_discount,
    )

    return rate_mul


@external
@view
def add_collateral_health_preview(
    _collateral: uint256,
    _for: address,
    _caller: address,
    _full: bool,
) -> int256:
    """
    @notice Calculates health after calling add_collateral with the same args
    @param _collateral Amount of collateral to add
    @param _for Address to add collateral for
    @param _caller Address from which add_collateral tx is going to be sent.
           Depending on this address liquidation_discount will be changed or not.
    @param _full Whether it's a 'full' health or not
    @return Signed health value
    """
    return staticcall self._view.add_collateral_health_preview(
        _collateral, _for, _caller, _full
    )


@external
def add_collateral(_collateral: uint256, _for: address = msg.sender):
    """
    @notice Add extra collateral to avoid bad liqidations
    @param _collateral Amount of collateral to add
    @param _for Address to add collateral for
    """
    if _collateral == 0:
        return
    self._add_collateral_borrow(_collateral, 0, _for, False, self._check_approval(_for))
    tkn.transfer_from(COLLATERAL_TOKEN, msg.sender, AMM.address, _collateral)
    self._save_rate()


@external
@view
def remove_collateral_health_preview(
    _collateral: uint256,
    _for: address,
    _full: bool,
) -> int256:
    """
    @notice Calculates health after calling remove_collateral with the same args
    @param _collateral Amount of collateral to remove
    @param _for Address to remove collateral from
    @param _full Whether it's a 'full' health or not
    @return Signed health value
    """
    return staticcall self._view.remove_collateral_health_preview(
        _collateral, _for, _full
    )


@external
def remove_collateral(_collateral: uint256, _for: address = msg.sender):
    """
    @notice Remove some collateral without repaying the debt
    @param _collateral Amount of collateral to remove
    @param _for Address to remove collateral for
    """
    if _collateral == 0:
        return
    assert self._check_approval(_for)
    self._add_collateral_borrow(_collateral, 0, _for, True, False)
    tkn.transfer_from(COLLATERAL_TOKEN, AMM.address, _for, _collateral)
    self._save_rate()


@external
@view
def borrow_more_health_preview(
    _collateral: uint256,
    _debt: uint256,
    _for: address,
    _full: bool,
) -> int256:
    """
    @notice Calculates health after calling borrow_more with the same params
    @param _collateral Amount of collateral to add (from wallet + callback).
           Note: the collateral amount coming from the callback should be included.
    @param _debt Amount of borrowed asset debt to take
    @param _for Address to borrow for
    @param _full Whether it's a 'full' health or not
    @return Signed health value
    """
    return staticcall self._view.borrow_more_health_preview(
        _collateral, _debt, _for, _full
    )


@external
def borrow_more(
    _collateral: uint256,
    _debt: uint256,
    _for: address = msg.sender,
    _callbacker: address = empty(address),
    _calldata: Bytes[CALLDATA_MAX_SIZE] = b"",
):
    """
    @notice Borrow more borrowed tokens while adding more collateral using a callback (to leverage more)
    @param _collateral Amount of collateral to add
    @param _debt Amount of borrowed asset debt to take
    @param _for Address to borrow for
    @param _callbacker Address of the callback contract
    @param _calldata Any data for callbacker
    """
    if _debt == 0:
        return
    assert self._check_approval(_for)

    more_collateral: uint256 = 0
    if _callbacker != empty(address):
        tkn.transfer(BORROWED_TOKEN, _callbacker, _debt)
        # If there is any unused debt, callbacker can send it to the user
        more_collateral = self.execute_callback(
            _callbacker,
            CALLBACK_DEPOSIT,
            _for,
            0,
            _collateral,
            _debt,
            _calldata,
        ).collateral

    rate_mul: uint256 = self._add_collateral_borrow(
        _collateral + more_collateral, _debt, _for, False, False
    )

    tkn.transfer_from(COLLATERAL_TOKEN, msg.sender, AMM.address, _collateral)
    tkn.transfer_from(COLLATERAL_TOKEN, _callbacker, AMM.address, more_collateral)
    if _callbacker == empty(address):
        tkn.transfer(BORROWED_TOKEN, _for, _debt)

    self._update_total_debt(_debt, rate_mul, True)
    self.lent += _debt
    self._save_rate()


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
def _repay_full(
    _for: address,
    _debt: uint256,  # same as _d_debt in this case
    _approval: bool,
    _xy: uint256[2],
    _cb: IController.CallbackData,
    _callbacker: address,
):
    if _callbacker == empty(address):
        _xy = extcall AMM.withdraw(_for, WAD)

    # ================= Recover borrowed tokens (xy[0]) =================
    non_wallet_d_debt: uint256 = _xy[0] + _cb.borrowed
    wallet_d_debt: uint256 = crv_math.sub_or_zero(_debt, non_wallet_d_debt)
    if _xy[0] > 0:  #  pull borrowed tokens from AMM (already soft liquidated)
        assert _approval  # dev: need approval to spend borrower's xy[0]
        tkn.transfer_from(BORROWED_TOKEN, AMM.address, self, _xy[0])
    tkn.transfer_from(BORROWED_TOKEN, _callbacker, self, _cb.borrowed)
    tkn.transfer_from(BORROWED_TOKEN, msg.sender, self, wallet_d_debt)
    tkn.transfer(BORROWED_TOKEN, _for, crv_math.sub_or_zero(non_wallet_d_debt, _debt))


    # ================= Recover collateral tokens (xy[1]) =================
    if _callbacker == empty(address):
        tkn.transfer_from(COLLATERAL_TOKEN, AMM.address, _for, _xy[1])
    else:
        tkn.transfer_from(COLLATERAL_TOKEN, _callbacker, _for, _cb.collateral)

    self._remove_from_list(_for)

    log IController.UserState(
        user=_for, collateral=0, borrowed=0, debt=0, n1=0, n2=0, liquidation_discount=0
    )
    log IController.Repay(
        user=_for, collateral_decrease=_xy[1], loan_decrease=_debt
    )


@internal
def _repay_partial(
    _for: address,
    _debt: uint256,
    _wallet_d_debt: uint256,
    _approval: bool,
    _xy: uint256[2],
    _cb: IController.CallbackData,
    _callbacker: address,
    _max_active_band: int256,
    _shrink: bool,
) -> uint256:
    assert _approval or not _shrink, "Need approval to shrink"
    # slippage-like check to prevent dos on repay (grief attack)
    active_band: int256 = staticcall AMM.active_band_with_skip()
    new_collateral: uint256 = _xy[1]
    if _callbacker != empty(address):
        active_band = _cb.active_band
        new_collateral = _cb.collateral
    assert active_band <= _max_active_band

    ns: int256[2] = staticcall AMM.read_user_tick_numbers(_for)
    size: int256 = unsafe_sub(ns[1], ns[0])
    if ns[0] <= active_band and _shrink:
        assert ns[1] >= active_band + MIN_TICKS, "Can't shrink"
        size = unsafe_sub(ns[1], active_band + 1)
    # _debt > _wallet_d_debt + cb.borrowed + xy[0] (check repay method)
    new_debt: uint256 = unsafe_sub(_debt, unsafe_add(_cb.borrowed, _wallet_d_debt))
    new_borrowed: uint256 = _xy[0]

    if ns[0] > active_band or _shrink:
        # Not underwater or shrink mode - can move bands
        if _callbacker == empty(address):
            _xy = extcall AMM.withdraw(_for, WAD)
            new_collateral = _xy[1]
        new_debt -= _xy[0]
        new_borrowed = 0

        ns[0] = staticcall self._view.calculate_debt_n1(
            new_collateral,
            new_debt,
            convert(unsafe_add(size, 1), uint256),
            _for,
        )
        ns[1] = ns[0] + size
        extcall AMM.deposit_range(_for, new_collateral, ns[0], ns[1])
    else:
        # Underwater without shrink - cannot use callback or move bands.
        # But can avoid a bad liquidation just reducing debt amount.
        assert _callbacker == empty(address)

    liquidation_discount: uint256 = self._update_user_liquidation_discount(_for, _approval, new_debt)

    # ================= Recover borrowed tokens (xy[0]) =================
    if _shrink:
        tkn.transfer_from(BORROWED_TOKEN, AMM.address, self, _xy[0])
    tkn.transfer_from(BORROWED_TOKEN, _callbacker, self, _cb.borrowed)
    tkn.transfer_from(BORROWED_TOKEN, msg.sender, self, _wallet_d_debt)

    # ================= Recover collateral tokens (xy[1]) =================
    tkn.transfer_from(COLLATERAL_TOKEN, _callbacker, AMM.address, _cb.collateral)

    d_debt: uint256 = _debt - new_debt

    log IController.UserState(
        user=_for,
        collateral=new_collateral,
        borrowed=new_borrowed,
        debt=new_debt,
        n1=ns[0],
        n2=ns[1],
        liquidation_discount=liquidation_discount,
    )
    log IController.Repay(
        user=_for,
        collateral_decrease=crv_math.sub_or_zero(_xy[1], new_collateral),
        loan_decrease=d_debt,
    )

    return d_debt


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
    @notice Calculates health after calling repay with the same params
    @dev Works only for partial repay, reverts for full repay
    @param _d_collateral Amount of collateral to remove (goes to callback)
    @param _d_debt The amount of debt to repay (from wallet + callback).
           Note: the borrowed amount coming from the callback should be included.
    @param _for Address to borrow for
    @param _caller Address from which repay tx is going to be sent.
           Depending on this address liquidation_discount will be changed or not.
    @param _shrink Whether shrink soft-liquidated part of the position or not
    @param _full Whether it's a 'full' health or not
    @return Signed health value
    """
    return staticcall self._view.repay_health_preview(
        _d_collateral, _d_debt, _for, _caller, _shrink, _full
    )


@external
def repay(
    _wallet_d_debt: uint256,
    _for: address = msg.sender,
    _max_active_band: int256 = max_value(int256),
    _callbacker: address = empty(address),
    _calldata: Bytes[CALLDATA_MAX_SIZE] = b"",
    _shrink: bool = False
):
    """
    @notice Repay debt (partially or fully)
    @param _wallet_d_debt The amount of debt to repay from user's wallet.
                   If it's max_value(uint256) or just higher than the current debt - will do full repayment.
    @param _for The user to repay the debt for
    @param _max_active_band Don't allow active band to be higher than this (to prevent front-running the repay)
    @param _callbacker Address of the callback contract
    @param _calldata Any data for callbacker
    @param _shrink Whether shrink soft-liquidated part of the position or not
    """
    debt: uint256 = 0
    rate_mul: uint256 = 0
    debt, rate_mul = self._debt(_for)
    self._check_loan_exists(debt)
    approval: bool = self._check_approval(_for)
    xy: uint256[2] = staticcall AMM.get_sum_xy(_for)

    cb: IController.CallbackData = empty(IController.CallbackData)
    if _callbacker != empty(address):
        assert approval # dev: need approval for callback
        xy = extcall AMM.withdraw(_for, WAD)
        tkn.transfer_from(COLLATERAL_TOKEN, AMM.address, _callbacker, xy[1])
        cb = self.execute_callback(
            _callbacker, CALLBACK_REPAY, _for, xy[0], xy[1], debt, _calldata
        )

    d_debt: uint256 = min(min(_wallet_d_debt, debt) + xy[0] + cb.borrowed, debt)
    assert d_debt > 0  # dev: no coins to repay

    if d_debt == debt:
        self._repay_full(_for, d_debt, approval, xy, cb, _callbacker)
    else:
        d_debt = self._repay_partial(
            _for,
            debt,
            _wallet_d_debt,
            approval,
            xy,
            cb,
            _callbacker,
            _max_active_band,
            _shrink,
        )
    debt -= d_debt

    self.loan[_for] = IController.Loan(initial_debt=debt, rate_mul=rate_mul)
    self._update_total_debt(d_debt, rate_mul, False)
    self.repaid += d_debt
    self._save_rate()


@external
@view
def tokens_to_shrink(_user: address, _d_collateral: uint256 = 0) -> uint256:
    """
    @notice Calculate the amount of borrowed asset required to shrink the user's position
    @param _user Address of the user to shrink the position for
    @param _d_collateral The amount of collateral from user's position which is going to be used by callback
    @return The amount of borrowed asset needed
    """
    return staticcall self._view.tokens_to_shrink(_user, _d_collateral)


@internal
@view
def _health(
    _user: address, _debt: uint256, _full: bool, _liquidation_discount: uint256
) -> int256:
    """
    @notice Returns position health normalized to 1e18 for the user.
            Liquidation starts when < 0, however devaluation of collateral doesn't cause liquidation
    @param _user User address to calculate health for
    @param _debt The amount of debt to calculate health for
    @param _full Whether to take into account the price difference above the highest user's band
    @param _liquidation_discount Liquidation discount to use (can be 0)
    @return Health: > 0 = good.
    """
    self._check_loan_exists(_debt)
    health: int256 = SWAD - convert(_liquidation_discount, int256)
    health = (
        unsafe_div(
            convert(staticcall AMM.get_x_down(_user), int256) * health,
            convert(_debt, int256),
        )
        - SWAD
    )

    if _full:
        ns0: int256 = (staticcall AMM.read_user_tick_numbers(_user))[0]  # ns[1] > ns[0]
        if ns0 > staticcall AMM.active_band():  # We are not in liquidation mode
            p: uint256 = staticcall AMM.price_oracle()
            p_up: uint256 = staticcall AMM.p_oracle_up(ns0)
            if p > p_up:
                health += convert(
                    unsafe_div(
                        unsafe_sub(p, p_up)
                        * (staticcall AMM.get_sum_xy(_user))[1]
                        * COLLATERAL_PRECISION,
                        _debt * BORROWED_PRECISION,
                    ),
                    int256,
                )
    return health


@internal
@pure
def _get_f_remove(_frac: uint256, _health_limit: uint256) -> uint256:
    # f_remove = ((1 + h / 2) / (1 + h) * (1 - frac) + frac) * frac
    if _health_limit == 0:
        return _frac
    if _frac == WAD:
        return WAD

    f_remove: uint256 = unsafe_div(
        unsafe_mul(
            unsafe_add(WAD, unsafe_div(_health_limit, 2)),
            unsafe_sub(WAD, _frac),
        ),
        unsafe_add(WAD, _health_limit),
    )

    return unsafe_div(unsafe_mul(unsafe_add(f_remove, _frac), _frac), WAD)


@external
@view
def liquidate_health_preview(
    _user: address,
    _caller: address,
    _frac: uint256,
    _full: bool,
) -> int256:
    """
    @notice Calculates health after calling liquidate with the same args
    @param _user User to liquidate
    @param _caller Address from which liquidate tx is going to be sent.
           Depending on this address liquidation_discount will be changed or not.
    @param _frac Fraction to liquidate; 100% = 10**18
    @param _full Whether it's a 'full' health or not
    @return Signed health value
    """
    return staticcall self._view.liquidate_health_preview(
        _user, _caller, _frac, _full
    )


@external
def liquidate(
    _user: address,
    _min_x: uint256,
    _frac: uint256 = 10**18,
    _callbacker: address = empty(address),
    _calldata: Bytes[CALLDATA_MAX_SIZE] = b"",
):
    """
    @notice Perform a bad liquidation (or self-liquidation) of user if health is not good
    @param _min_x Minimal amount of borrowed asset to receive (to avoid liquidators being sandwiched)
    @param _frac Fraction to liquidate; 100% = 10**18
    @param _callbacker Address of the callback contract
    @param _calldata Any data for callbacker
    """
    approval: bool = self._check_approval(_user)
    liquidation_discount: uint256 = self.liquidation_discounts[_user]
    debt: uint256 = 0
    rate_mul: uint256 = 0
    debt, rate_mul = self._debt(_user)

    health_before: int256 = self._health(_user, debt, True, liquidation_discount)
    health_limit: uint256 = 0
    if not approval:
        assert health_before < 0, "Not enough rekt"
        health_limit = liquidation_discount

    final_debt: uint256 = debt
    assert _frac <= WAD, "frac>100%"
    debt = unsafe_div(debt * _frac + (WAD - 1), WAD)
    assert debt > 0
    final_debt = unsafe_sub(final_debt, debt)

    # If liquidating entire debt, ensure full collateral withdrawal
    f_remove: uint256 = self._get_f_remove(_frac, health_limit)
    if final_debt == 0:
        f_remove = WAD

    # Withdraw sender's borrowed and collateral to our contract
    # When frac is set - we withdraw a bit less for the same debt fraction
    # f_remove = ((1 + h/2) / (1 + h) * (1 - frac) + frac) * frac
    # where h is health limit.
    # This is less than full h discount but more than no discount
    xy: uint256[2] = extcall AMM.withdraw(_user, f_remove)  # [stable, collateral]

    # x increase in same block -> price up -> good
    # x decrease in same block -> price down -> bad
    assert xy[0] >= _min_x, "Slippage"

    min_amm_burn: uint256 = min(xy[0], debt)
    tkn.transfer_from(BORROWED_TOKEN, AMM.address, self, min_amm_burn)

    if debt > xy[0]:
        to_repay: uint256 = unsafe_sub(debt, xy[0])

        if _callbacker == empty(address):
            # Withdraw collateral if no callback is present
            tkn.transfer_from(COLLATERAL_TOKEN, AMM.address, msg.sender, xy[1])
            # Request what's left from user
            tkn.transfer_from(BORROWED_TOKEN, msg.sender, self, to_repay)

        else:
            # Move collateral to callbacker, call it and remove everything from it back in
            tkn.transfer_from(COLLATERAL_TOKEN, AMM.address, _callbacker, xy[1])
            # Callback
            cb: IController.CallbackData = self.execute_callback(
                _callbacker,
                CALLBACK_LIQUIDATE,
                _user,
                xy[0],
                xy[1],
                debt,
                _calldata,
            )
            assert cb.borrowed >= to_repay, "no enough proceeds"
            tkn.transfer_from(BORROWED_TOKEN, _callbacker, self, to_repay)
            tkn.transfer_from(BORROWED_TOKEN, _callbacker, msg.sender, crv_math.sub_or_zero(cb.borrowed, to_repay))
            tkn.transfer_from(COLLATERAL_TOKEN, _callbacker, msg.sender, cb.collateral)
    else:
        # Withdraw collateral
        tkn.transfer_from(COLLATERAL_TOKEN, AMM.address, msg.sender, xy[1])
        # xy[0] >= debt
        tkn.transfer_from(BORROWED_TOKEN, AMM.address, msg.sender, unsafe_sub(xy[0], debt))

    self.loan[_user] = IController.Loan(initial_debt=final_debt, rate_mul=rate_mul)
    self._update_total_debt(debt, rate_mul, False)
    self.repaid += debt
    self._save_rate()

    log IController.Repay(
        user=_user, collateral_decrease=xy[1], loan_decrease=debt
    )
    log IController.Liquidate(
        liquidator=msg.sender,
        user=_user,
        collateral_received=xy[1],
        borrowed_received=xy[0],
        debt=debt,
    )
    if final_debt == 0:
        log IController.UserState(
            user=_user, collateral=0, borrowed=0, debt=0, n1=0, n2=0, liquidation_discount=0
        )
        self._remove_from_list(_user)
    else:
        if health_before > 0:
            liquidation_discount = self._update_user_liquidation_discount(_user, approval, final_debt)
        else:
            # Passing new_debt == 0 means the action can end with unhealthy state
            liquidation_discount = self._update_user_liquidation_discount(_user, approval, 0)

        xy = staticcall AMM.get_sum_xy(_user)
        ns: int256[2] = staticcall AMM.read_user_tick_numbers(_user)  # ns[1] > ns[0]
        log IController.UserState(
            user=_user,
            collateral=xy[1],
            borrowed=xy[0],
            debt=final_debt,
            n1=ns[0],
            n2=ns[1],
            liquidation_discount=liquidation_discount
        )


@external
@view
def tokens_to_liquidate(_user: address, _frac: uint256 = WAD) -> uint256:
    """
    @notice Calculate the amount of borrowed asset to have in liquidator's wallet to liquidate a user
    @param _user Address of the user to liquidate
    @param _frac Fraction to liquidate; 100% = 10**18
    @return The amount of borrowed asset needed
    """
    assert _frac <= WAD, "frac>100%"
    health_limit: uint256 = 0
    if not self._check_approval(_user):
        health_limit = self.liquidation_discounts[_user]
    borrowed: uint256 = unsafe_div(
        (staticcall AMM.get_sum_xy(_user))[0]
        * self._get_f_remove(_frac, health_limit),
        WAD,
    )
    debt: uint256 = unsafe_div(self._debt(_user)[0] * _frac + (WAD - 1), WAD)

    return crv_math.sub_or_zero(debt, borrowed)


@external
@view
def health(_user: address, _full: bool = False) -> int256:
    """
    @notice Returns position health normalized to 1e18 for the user.
            Liquidation starts when < 0, however devaluation of collateral doesn't cause liquidation
    """
    return self._health(
        _user, self._debt(_user)[0], _full, self.liquidation_discounts[_user]
    )


@external
@view
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


@external
@view
@reentrant
def amm_price() -> uint256:
    """
    @notice Current price from the AMM
    @dev Marked as reentrant because AMM already has a nonreentrant decorator
    """
    return staticcall AMM.get_p()


@external
@view
def user_prices(_user: address) -> uint256[2]:  # Upper, lower
    """
    @notice Lowest price of the lower band and highest price of the upper band the user has deposit in the AMM
    @param _user User address
    @return (upper_price, lower_price)
    """
    return staticcall self._view.user_prices(_user)


@external
@view
def user_state(_user: address) -> uint256[4]:
    """
    @notice Return the user state in one call
    @param _user User to return the state for
    @return (collateral, borrowed, debt, N)
    """
    return staticcall self._view.user_state(_user)


@external
@reentrant
def set_amm_fee(_fee: uint256):
    """
    @notice Set the AMM fee (factory admin only)
    @dev Reentrant because AMM is nonreentrant
    @param _fee The fee which should be no higher than MAX_AMM_FEE
    """
    self._check_admin()
    assert _fee <= MAX_AMM_FEE and _fee >= MIN_AMM_FEE, "Fee"
    extcall AMM.set_fee(_fee)


@external
def set_monetary_policy(_monetary_policy: IMonetaryPolicy):
    """
    @notice Set monetary policy contract
    @param _monetary_policy Address of the monetary policy contract
    """
    self._check_admin()
    self._monetary_policy = _monetary_policy
    extcall _monetary_policy.rate_write()
    log IController.SetMonetaryPolicy(monetary_policy=_monetary_policy)


@internal
def _set_borrowing_discounts(
        _loan_discount: uint256, _liquidation_discount: uint256
):
    assert _liquidation_discount > 0 # dev: liquidation discount = 0
    assert _loan_discount < WAD # dev: loan discount >= 100%
    assert _loan_discount > _liquidation_discount # dev: loan discount <= liquidation discount
    self.liquidation_discount = _liquidation_discount
    self.loan_discount = _loan_discount
    log IController.SetBorrowingDiscounts(
        loan_discount=_loan_discount, liquidation_discount=_liquidation_discount
    )


@external
def set_borrowing_discounts(
    _loan_discount: uint256, _liquidation_discount: uint256
):
    """
    @notice Set discounts at which we can borrow (defines max LTV) and where bad liquidation starts
    @param _loan_discount Discount which defines LTV
    @param _liquidation_discount Discount where bad liquidation starts
    """
    self._check_admin()
    self._set_borrowing_discounts(_loan_discount, _liquidation_discount)


@external
def set_callback(_cb: ILMGauge):
    """
    @notice Set liquidity mining callback
    """
    self._check_admin()
    extcall AMM.set_callback(_cb)
    log IController.SetLMCallback(callback=_cb)


@external
def collect_fees() -> uint256:
    """
    @notice Collect the fees charged as interest.
    """
    return self._collect_fees()


@internal
def _collect_fees() -> uint256:
    rate_mul: uint256 = staticcall AMM.get_rate_mul()
    loan: IController.Loan = self._update_total_debt(0, rate_mul, False)

    pending_admin_fees: uint256 = self.admin_fees
    self.collected += pending_admin_fees
    self.admin_fees = 0
    tkn.transfer(BORROWED_TOKEN, staticcall FACTORY.fee_receiver(), pending_admin_fees)

    self._save_rate()
    log IController.CollectFees(amount=pending_admin_fees, new_debt=loan.initial_debt)

    return pending_admin_fees


@external
@reentrant
def _on_debt_increased(_delta: uint256, _total_debt: uint256):
    pass


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
    assert _value < WAD, "extra_health too high"
    self.extra_health[msg.sender] = _value
    log IController.SetExtraHealth(user=msg.sender, health=_value)
