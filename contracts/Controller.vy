# pragma version 0.4.1
# pragma optimize codesize
# pragma evm-version shanghai
"""
@title crvUSD Controller
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
"""

from snekmate.utils import math
from ethereum.ercs import IERC20
from ethereum.ercs import IERC20Detailed


interface LLAMMA:
    def A() -> uint256: view
    def get_p() -> uint256: view
    def get_base_price() -> uint256: view
    def active_band() -> int256: view
    def active_band_with_skip() -> int256: view
    def p_oracle_up(n: int256) -> uint256: view
    def p_oracle_down(n: int256) -> uint256: view
    def deposit_range(user: address, amount: uint256, n1: int256, n2: int256): nonpayable
    def read_user_tick_numbers(_for: address) -> int256[2]: view
    def get_sum_xy(user: address) -> uint256[2]: view
    def withdraw(user: address, frac: uint256) -> uint256[2]: nonpayable
    def get_x_down(user: address) -> uint256: view
    def get_rate_mul() -> uint256: view
    def set_rate(rate: uint256) -> uint256: nonpayable
    def set_fee(fee: uint256): nonpayable
    def price_oracle() -> uint256: view
    def can_skip_bands(n_end: int256) -> bool: view
    def has_liquidity(user: address) -> bool: view
    def bands_x(n: int256) -> uint256: view
    def bands_y(n: int256) -> uint256: view
    def set_callback(user: address): nonpayable

interface MonetaryPolicy:
    def rate_write() -> uint256: nonpayable

interface Factory:
    def stablecoin() -> address: view
    def admin() -> address: view
    def fee_receiver() -> address: view


event UserState:
    user: indexed(address)
    collateral: uint256
    debt: uint256
    n1: int256
    n2: int256
    liquidation_discount: uint256

event Borrow:
    user: indexed(address)
    collateral_increase: uint256
    loan_increase: uint256

event Repay:
    user: indexed(address)
    collateral_decrease: uint256
    loan_decrease: uint256

event RemoveCollateral:
    user: indexed(address)
    collateral_decrease: uint256

event Liquidate:
    liquidator: indexed(address)
    user: indexed(address)
    collateral_received: uint256
    stablecoin_received: uint256
    debt: uint256

event SetMonetaryPolicy:
    monetary_policy: address

event SetBorrowingDiscounts:
    loan_discount: uint256
    liquidation_discount: uint256

event SetExtraHealth:
    user: indexed(address)
    health: uint256

event CollectFees:
    amount: uint256
    new_supply: uint256

event SetLMCallback:
    callback: address

event Approval:
    owner: indexed(address)
    spender: indexed(address)
    allow: bool


struct Loan:
    initial_debt: uint256
    rate_mul: uint256

struct Position:
    user: address
    x: uint256
    y: uint256
    debt: uint256
    health: int256

struct CallbackData:
    active_band: int256
    stablecoins: uint256
    collateral: uint256


FACTORY: immutable(Factory)
MAX_LOAN_DISCOUNT: constant(uint256) = 5 * 10**17
MIN_LIQUIDATION_DISCOUNT: constant(uint256) = 10**16 # Start liquidating when threshold reached
MAX_TICKS: constant(int256) = 50
MAX_TICKS_UINT: constant(uint256) = 50
MIN_TICKS: constant(int256) = 4
MIN_TICKS_UINT: constant(uint256) = 4
MAX_SKIP_TICKS: constant(uint256) = 1024
MAX_P_BASE_BANDS: constant(int256) = 5

MAX_RATE: constant(uint256) = 43959106799  # 300% APY

loan: HashMap[address, Loan]
liquidation_discounts: public(HashMap[address, uint256])
_total_debt: Loan

loans: public(address[2**64 - 1])  # Enumerate existing loans
loan_ix: public(HashMap[address, uint256])  # Position of the loan in the list
n_loans: public(uint256)  # Number of nonzero loans

minted: public(uint256)
redeemed: public(uint256)

monetary_policy: public(MonetaryPolicy)
liquidation_discount: public(uint256)
loan_discount: public(uint256)

COLLATERAL_TOKEN: immutable(IERC20)
COLLATERAL_PRECISION: immutable(uint256)

BORROWED_TOKEN: immutable(IERC20)
BORROWED_PRECISION: immutable(uint256)

AMM: immutable(LLAMMA)
A: immutable(uint256)
Aminus1: immutable(uint256)
LOGN_A_RATIO: immutable(int256)  # log(A / (A - 1))
SQRT_BAND_RATIO: immutable(uint256)

MIN_AMM_FEE: constant(uint256) = 10**6  # 1e-12, still needs to be above 0
MAX_AMM_FEE: immutable(uint256)  # let's set to MIN_TICKS / A: for example, 4% max fee for A=100

CALLBACK_DEPOSIT: constant(bytes4) = method_id("callback_deposit(address,uint256,uint256,uint256,bytes)", output_type=bytes4)
CALLBACK_REPAY: constant(bytes4) = method_id("callback_repay(address,uint256,uint256,uint256,bytes)", output_type=bytes4)
CALLBACK_LIQUIDATE: constant(bytes4) = method_id("callback_liquidate(address,uint256,uint256,uint256,bytes)", output_type=bytes4)

DEAD_SHARES: constant(uint256) = 1000

approval: public(HashMap[address, HashMap[address, bool]])
extra_health: public(HashMap[address, uint256])


@deploy
def __init__(
        collateral_token: address,
        monetary_policy: address,
        loan_discount: uint256,
        liquidation_discount: uint256,
        amm: address):
    """
    @notice Controller constructor deployed by the factory from blueprint
    @param collateral_token Token to use for collateral
    @param monetary_policy Address of monetary policy
    @param loan_discount Discount of the maximum loan size compare to get_x_down() value
    @param liquidation_discount Discount of the maximum loan size compare to
           get_x_down() for "bad liquidation" purposes
    @param amm AMM address (Already deployed from blueprint)
    """
    FACTORY = Factory(msg.sender)

    self.monetary_policy = MonetaryPolicy(monetary_policy)

    self.liquidation_discount = liquidation_discount
    self.loan_discount = loan_discount
    self._total_debt.rate_mul = 10**18

    AMM = LLAMMA(amm)
    _A: uint256 = staticcall LLAMMA(amm).A()
    A = _A
    Aminus1 = unsafe_sub(_A, 1)
    LOGN_A_RATIO = math._wad_ln(convert(unsafe_div(_A * 10**18, unsafe_sub(_A, 1)), int256))
    MAX_AMM_FEE = min(unsafe_div(10**18 * MIN_TICKS_UINT, A), 10**17)

    COLLATERAL_TOKEN = IERC20(collateral_token)
    collateral_decimals: uint256 = convert(staticcall IERC20Detailed(COLLATERAL_TOKEN.address).decimals(), uint256)
    COLLATERAL_PRECISION = pow_mod256(10, 18 - collateral_decimals)

    BORROWED_TOKEN = IERC20(staticcall Factory(msg.sender).stablecoin())
    borrowed_decimals: uint256 = convert(staticcall IERC20Detailed(BORROWED_TOKEN.address).decimals(), uint256)
    BORROWED_PRECISION = pow_mod256(10, 18 - borrowed_decimals)

    SQRT_BAND_RATIO = isqrt(unsafe_div(10**36 * _A, unsafe_sub(_A, 1)))

    assert extcall BORROWED_TOKEN.approve(msg.sender, max_value(uint256), default_return_value=True)


@external
@view
def factory() -> address:
    """
    @notice Address of the factory
    """
    return FACTORY.address


@external
@view
def amm() -> LLAMMA:
    """
    @notice Address of the AMM
    """
    return AMM


@external
@view
def collateral_token() -> IERC20:
    """
    @notice Address of the collateral token
    """
    return COLLATERAL_TOKEN


@external
@view
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
    rate: uint256 = min(extcall self.monetary_policy.rate_write(), MAX_RATE)
    extcall AMM.set_rate(rate)


@external
@nonreentrant
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
    loan: Loan = self.loan[user]
    if loan.initial_debt == 0:
        return (0, rate_mul)
    else:
        # Let user repay 1 smallest decimal more so that the system doesn't lose on precision
        # Use ceil div
        debt: uint256 = loan.initial_debt * rate_mul
        if debt % loan.rate_mul > 0:  # if only one loan -> don't have to do it
            if self.n_loans > 1:
                debt += unsafe_sub(loan.rate_mul, 1)
        debt = unsafe_div(debt, loan.rate_mul)  # loan.rate_mul is nonzero because we just had % successful
        return (debt, rate_mul)


@external
@view
@nonreentrant
def debt(user: address) -> uint256:
    """
    @notice Get the value of debt without changing the state
    @param user User address
    @return Value of debt
    """
    return self._debt(user)[0]


@external
@view
@nonreentrant
def loan_exists(user: address) -> bool:
    """
    @notice Check whether there is a loan of `user` in existence
    """
    return self.loan[user].initial_debt > 0


@internal
@view
def _get_total_debt() -> uint256:
    """
    @notice Total debt of this controller
    """
    rate_mul: uint256 = staticcall AMM.get_rate_mul()
    loan: Loan = self._total_debt
    return loan.initial_debt * rate_mul // loan.rate_mul


# No decorator because used in monetary policy
@external
@view 
def total_debt() -> uint256:
    """
    @notice Total debt of this controller
    """
    return self._get_total_debt()


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
    d_y_effective: uint256 = unsafe_div(
        collateral * unsafe_sub(
            10**18, min(discount + unsafe_div((DEAD_SHARES * 10**18), max(unsafe_div(collateral, N), DEAD_SHARES)), 10**18)
        ),
        unsafe_mul(SQRT_BAND_RATIO, N))
    y_effective: uint256 = d_y_effective
    for i: uint256 in range(1, MAX_TICKS_UINT):
        if i == N:
            break
        d_y_effective = unsafe_div(d_y_effective * Aminus1, A)
        y_effective = unsafe_add(y_effective, d_y_effective)
    return y_effective


@internal
@view
def _calculate_debt_n1(collateral: uint256, debt: uint256, N: uint256, user: address) -> int256:
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
    y_effective: uint256 = self.get_y_effective(collateral * COLLATERAL_PRECISION, N, self.loan_discount + self.extra_health[user])
    # p_oracle_up(n1) = base_price * ((A - 1) / A)**n1

    # We borrow up until min band touches p_oracle,
    # or it touches non-empty bands which cannot be skipped.
    # We calculate required n1 for given (collateral, debt),
    # and if n1 corresponds to price_oracle being too high, or unreachable band
    # - we revert.

    # n1 is band number based on adiabatic trading, e.g. when p_oracle ~ p
    y_effective = unsafe_div(y_effective * p_base, debt * BORROWED_PRECISION + 1)  # Now it's a ratio

    # n1 = floor(log(y_effective) / self.logAratio)
    # EVM semantics is not doing floor unlike Python, so we do this
    assert y_effective > 0, "Amount too low"
    n1: int256 = math._wad_ln(convert(y_effective, int256)) 
    if n1 < 0:
        n1 -= unsafe_sub(LOGN_A_RATIO, 1)  # This is to deal with vyper's rounding of negative numbers
    n1 = unsafe_div(n1, LOGN_A_RATIO)

    n1 = min(n1, 1024 - convert(N, int256)) + n0
    if n1 <= n0:
        assert staticcall AMM.can_skip_bands(n1 - 1), "Debt too high"

    # Let's not rely on active_band corresponding to price_oracle:
    # this will be not correct if we are in the area of empty bands
    assert staticcall AMM.p_oracle_up(n1) < staticcall AMM.price_oracle(), "Debt too high"

    return n1


@internal
@view
def max_p_base() -> uint256:
    """
    @notice Calculate max base price including skipping bands
    """
    p_oracle: uint256 = staticcall AMM.price_oracle()
    # Should be correct unless price changes suddenly by MAX_P_BASE_BANDS+ bands
    n1: int256 = math._wad_ln(convert(staticcall AMM.get_base_price() * 10**18 // p_oracle, int256))
    if n1 < 0:
        n1 -= LOGN_A_RATIO - 1  # This is to deal with vyper's rounding of negative numbers
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

    y_effective: uint256 = self.get_y_effective(collateral * COLLATERAL_PRECISION, N,
                                                self.loan_discount + self.extra_health[user])

    x: uint256 = unsafe_sub(max(unsafe_div(y_effective * self.max_p_base(), 10**18), 1), 1)
    x = unsafe_div(x * (10**18 - 10**14), unsafe_mul(10**18, BORROWED_PRECISION))  # Make it a bit smaller
    return min(x, staticcall BORROWED_TOKEN.balanceOf(self) + current_debt)  # Cannot borrow beyond the amount of coins Controller has


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
            debt * unsafe_mul(10**18, BORROWED_PRECISION) // self.max_p_base() * 10**18 // self.get_y_effective(10**18, N, self.loan_discount + self.extra_health[user]) + unsafe_add(unsafe_mul(N, unsafe_add(N, 2 * DEAD_SHARES)), unsafe_sub(COLLATERAL_PRECISION, 1)),
            COLLATERAL_PRECISION
        ) * 10**18,
        10**18 - 10**14)


@external
@view
@nonreentrant
def calculate_debt_n1(collateral: uint256, debt: uint256, N: uint256, user: address = empty(address)) -> int256:
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
        assert extcall token.transferFrom(_from, _to, amount, default_return_value=True)


@internal
def transfer(token: IERC20, _to: address, amount: uint256):
    if amount > 0:
        assert extcall token.transfer(_to, amount, default_return_value=True)


@internal
def execute_callback(callbacker: address, callback_sig: bytes4, user: address, stablecoins: uint256,
                     collateral: uint256, debt: uint256, calldata: Bytes[10**4]) -> CallbackData:
    assert callbacker != COLLATERAL_TOKEN.address
    assert callbacker != BORROWED_TOKEN.address

    data: CallbackData = empty(CallbackData)
    data.active_band = staticcall AMM.active_band()
    band_x: uint256 = staticcall AMM.bands_x(data.active_band)
    band_y: uint256 = staticcall AMM.bands_y(data.active_band)

    # Callback
    response: Bytes[64] = raw_call(
        callbacker,
        concat(callback_sig, abi_encode(user, stablecoins, collateral, debt, calldata)),
        max_outsize=64
    )
    data.stablecoins = convert(slice(response, 0, 32), uint256)
    data.collateral = convert(slice(response, 32, 32), uint256)

    # Checks after callback
    assert data.active_band == staticcall AMM.active_band()
    assert band_x == staticcall AMM.bands_x(data.active_band)
    assert band_y == staticcall AMM.bands_y(data.active_band)

    return data

@internal
def _create_loan(collateral: uint256, debt: uint256, N: uint256, _for: address):
    assert self.loan[_for].initial_debt == 0, "Loan already created"
    assert N > MIN_TICKS_UINT - 1, "Need more ticks"
    assert N < MAX_TICKS_UINT + 1, "Need less ticks"

    n1: int256 = self._calculate_debt_n1(collateral, debt, N, _for)
    n2: int256 = n1 + convert(unsafe_sub(N, 1), int256)

    rate_mul: uint256 = staticcall AMM.get_rate_mul()
    self.loan[_for] = Loan(initial_debt=debt, rate_mul=rate_mul)
    liquidation_discount: uint256 = self.liquidation_discount
    self.liquidation_discounts[_for] = liquidation_discount

    n_loans: uint256 = self.n_loans
    self.loans[n_loans] = _for
    self.loan_ix[_for] = n_loans
    self.n_loans = unsafe_add(n_loans, 1)

    self._total_debt.initial_debt = self._total_debt.initial_debt * rate_mul // self._total_debt.rate_mul + debt
    self._total_debt.rate_mul = rate_mul

    extcall AMM.deposit_range(_for, collateral, n1, n2)
    self.minted += debt

    self._save_rate()

    log UserState(user=_for, collateral=collateral, debt=debt, n1=n1, n2=n2, liquidation_discount=liquidation_discount)
    log Borrow(user=_for, collateral_increase=collateral, loan_increase=debt)


@external
@nonreentrant
def create_loan(collateral: uint256, debt: uint256, N: uint256, _for: address = msg.sender, callbacker: address = empty(address), calldata: Bytes[10**4] = b""):
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
    if _for != tx.origin:
        # We can create a loan for tx.origin (for example when wrapping ETH with EOA),
        # however need to approve in other cases
        assert self._check_approval(_for)

    more_collateral: uint256 = 0
    if callbacker != empty(address):
        self.transfer(BORROWED_TOKEN, callbacker, debt)
        # If there is any unused debt, callbacker can send it to the user
        more_collateral = self.execute_callback(
            callbacker, CALLBACK_DEPOSIT, _for, 0, collateral, debt, calldata).collateral

    self._create_loan(collateral + more_collateral, debt, N, _for)

    self.transferFrom(COLLATERAL_TOKEN, msg.sender, AMM.address, collateral)
    if more_collateral > 0:
        self.transferFrom(COLLATERAL_TOKEN, callbacker, AMM.address, more_collateral)
    if callbacker == empty(address):
        self.transfer(BORROWED_TOKEN, _for, debt)


@internal
def _add_collateral_borrow(d_collateral: uint256, d_debt: uint256, _for: address, remove_collateral: bool,
                           check_rounding: bool):
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
    assert debt > 0, "Loan doesn't exist"
    debt += d_debt

    xy: uint256[2] = extcall AMM.withdraw(_for, 10**18)
    assert xy[0] == 0, "Already in underwater mode"
    if remove_collateral:
        xy[1] -= d_collateral
    else:
        xy[1] += d_collateral
        if check_rounding:
            # We need d(x + p*y) > 1 wei. For that, we do an equivalent check (but with x2 for safety)
            # This check is only needed when we add collateral for someone else, so gas is not an issue
            # 2 * 10**(18 - borrow_decimals + collateral_decimals) =
            # = 2 * 10**18 * 10**(18 - borrow_decimals) / 10**(collateral_decimals)
            assert d_collateral * staticcall AMM.price_oracle() > 2 * 10**18 * BORROWED_PRECISION // COLLATERAL_PRECISION

    ns: int256[2] = staticcall AMM.read_user_tick_numbers(_for)
    size: uint256 = convert(unsafe_add(unsafe_sub(ns[1], ns[0]), 1), uint256)
    n1: int256 = self._calculate_debt_n1(xy[1], debt, size, _for)
    n2: int256 = n1 + unsafe_sub(ns[1], ns[0])

    extcall AMM.deposit_range(_for, xy[1], n1, n2)
    self.loan[_for] = Loan(initial_debt=debt, rate_mul=rate_mul)

    liquidation_discount: uint256 = 0
    if _for == msg.sender:
        liquidation_discount = self.liquidation_discount
        self.liquidation_discounts[_for] = liquidation_discount
    else:
        liquidation_discount = self.liquidation_discounts[_for]

    if d_debt != 0:
        self._total_debt.initial_debt = self._total_debt.initial_debt * rate_mul // self._total_debt.rate_mul + d_debt
        self._total_debt.rate_mul = rate_mul

    if remove_collateral:
        log RemoveCollateral(user=_for, collateral_decrease=d_collateral)
    else:
        log Borrow(user=_for, collateral_increase=d_collateral, loan_increase=d_debt)

    log UserState(user=_for, collateral=xy[1], debt=debt, n1=n1, n2=n2, liquidation_discount=liquidation_discount)


@external
@nonreentrant
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
@nonreentrant
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
@nonreentrant
def borrow_more(collateral: uint256, debt: uint256, _for: address = msg.sender, callbacker: address = empty(address), calldata: Bytes[10**4] = b""):
    """
    @notice Borrow more stablecoins while adding more collateral using a callback (to leverage more)
    @param collateral Amount of collateral to add
    @param debt Amount of stablecoin debt to take
    @param _for Address to borrow for
    @param callbacker Address of the callback contract
    @param calldata Any data for callbacker
    """
    if debt == 0:
        return
    assert self._check_approval(_for)

    more_collateral: uint256 = 0
    if callbacker != empty(address):
        self.transfer(BORROWED_TOKEN, callbacker, debt)
        # If there is any unused debt, callbacker can send it to the user
        more_collateral = self.execute_callback(
            callbacker, CALLBACK_DEPOSIT, _for, 0, collateral, debt, calldata).collateral

    self._add_collateral_borrow(collateral + more_collateral, debt, _for, False, False)
    self.minted += debt
    self.transferFrom(COLLATERAL_TOKEN, msg.sender, AMM.address, collateral)
    if more_collateral > 0:
        self.transferFrom(COLLATERAL_TOKEN, callbacker, AMM.address, more_collateral)
    if callbacker == empty(address):
        self.transfer(BORROWED_TOKEN, _for, debt)
    self._save_rate()


@internal
def _remove_from_list(_for: address):
    last_loan_ix: uint256 = self.n_loans - 1
    loan_ix: uint256 = self.loan_ix[_for]
    assert self.loans[loan_ix] == _for  # dev: should never fail but safety first
    self.loan_ix[_for] = 0
    if loan_ix < last_loan_ix:  # Need to replace
        last_loan: address = self.loans[last_loan_ix]
        self.loans[loan_ix] = last_loan
        self.loan_ix[last_loan] = loan_ix
    self.n_loans = last_loan_ix


@external
@nonreentrant
def repay(_d_debt: uint256, _for: address = msg.sender, max_active_band: int256 = max_value(int256),
          callbacker: address = empty(address), calldata: Bytes[10**4] = b""):
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
    assert debt > 0, "Loan doesn't exist"
    approval: bool = self._check_approval(_for)
    xy: uint256[2] = empty(uint256[2])

    cb: CallbackData = empty(CallbackData)
    if callbacker != empty(address):
        assert approval
        xy = extcall AMM.withdraw(_for, 10 ** 18)
        self.transferFrom(COLLATERAL_TOKEN, AMM.address, callbacker, xy[1])
        cb = self.execute_callback(
            callbacker, CALLBACK_REPAY, _for, xy[0], xy[1], debt, calldata)

    total_stablecoins: uint256 = _d_debt + xy[0] + cb.stablecoins
    assert total_stablecoins > 0  # dev: no coins to repay
    d_debt: uint256 = 0

    # If we have more stablecoins than the debt - full repayment and closing the position
    if total_stablecoins >= debt:
        d_debt = debt
        debt = 0
        if callbacker == empty(address):
            xy = extcall AMM.withdraw(_for, 10 ** 18)

        # Transfer all stablecoins to self
        if xy[0] > 0:
            # Only allow full repayment when underwater for the sender to do
            assert approval
            self.transferFrom(BORROWED_TOKEN, AMM.address, self, xy[0])
        if cb.stablecoins > 0:
            self.transferFrom(BORROWED_TOKEN, callbacker, self, cb.stablecoins)
        if _d_debt > 0:
            self.transferFrom(BORROWED_TOKEN, msg.sender, self, _d_debt)

        # Transfer stablecoins excess to _for
        if total_stablecoins > d_debt:
            self.transfer(BORROWED_TOKEN, _for, unsafe_sub(total_stablecoins, d_debt))
        # Transfer collateral to _for
        if callbacker == empty(address):
            if xy[1] > 0:
                self.transferFrom(COLLATERAL_TOKEN, AMM.address, _for, xy[1])
        else:
            if cb.collateral > 0:
                self.transferFrom(COLLATERAL_TOKEN, callbacker, _for, cb.collateral)

        log UserState(user=_for, collateral=0, debt=0, n1=0, n2=0, liquidation_discount=0)
        log Repay(user=_for, collateral_decrease=xy[1], loan_decrease=d_debt)
        self._remove_from_list(_for)
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
                xy = extcall AMM.withdraw(_for, 10**18)
                new_collateral = xy[1]
            ns[0] = self._calculate_debt_n1(new_collateral, debt, convert(unsafe_add(size, 1), uint256), _for)
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

        log UserState(user=_for, collateral=xy[1], debt=debt, n1=ns[0], n2=ns[1], liquidation_discount=liquidation_discount)
        log Repay(user=_for, collateral_decrease=0, loan_decrease=d_debt)

    self.redeemed += d_debt

    self.loan[_for] = Loan(initial_debt=debt, rate_mul=rate_mul)
    total_debt: uint256 = self._total_debt.initial_debt * rate_mul // self._total_debt.rate_mul
    self._total_debt.initial_debt = unsafe_sub(max(total_debt, d_debt), d_debt)
    self._total_debt.rate_mul = rate_mul

    self._save_rate()


@internal
@view
def _health(user: address, debt: uint256, full: bool, liquidation_discount: uint256) -> int256:
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
    health = unsafe_div(convert(staticcall AMM.get_x_down(user), int256) * health, convert(debt, int256)) - 10**18

    if full:
        ns0: int256 = (staticcall AMM.read_user_tick_numbers(user))[0] # ns[1] > ns[0]
        if ns0 > staticcall AMM.active_band():  # We are not in liquidation mode
            p: uint256 = staticcall AMM.price_oracle()
            p_up: uint256 = staticcall AMM.p_oracle_up(ns0)
            if p > p_up:
                health += convert(unsafe_div(unsafe_sub(p, p_up) * (staticcall AMM.get_sum_xy(user))[1] * COLLATERAL_PRECISION, debt * BORROWED_PRECISION), int256)

    return health


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
        collateral = convert((staticcall AMM.get_sum_xy(user))[1], int256) + d_collateral
        n1 = self._calculate_debt_n1(convert(collateral, uint256), convert(debt, uint256), n, user)
        collateral *= convert(COLLATERAL_PRECISION, int256)  # now has 18 decimals
    else:
        n1 = ns[0]
        x_eff = convert(staticcall AMM.get_x_down(user) * unsafe_mul(10**18, BORROWED_PRECISION), int256)

    debt *= convert(BORROWED_PRECISION, int256)

    p0: int256 = convert(staticcall AMM.p_oracle_up(n1), int256)
    if ns[0] > active_band:
        x_eff = convert(self.get_y_effective(convert(collateral, uint256), n, 0), int256) * p0

    health: int256 = unsafe_div(x_eff, debt)
    health = health - unsafe_div(health * ld, 10**18) - 10**18

    if full:
        if n1 > active_band:  # We are not in liquidation mode
            p_diff: int256 = max(p0, convert(staticcall AMM.price_oracle(), int256)) - p0
            if p_diff > 0:
                health += unsafe_div(p_diff * collateral, debt)

    return health


@internal
@pure
def _get_f_remove(frac: uint256, health_limit: uint256) -> uint256:
    # f_remove = ((1 + h / 2) / (1 + h) * (1 - frac) + frac) * frac
    f_remove: uint256 = 10 ** 18
    if frac < 10 ** 18:
        f_remove = unsafe_div(unsafe_mul(unsafe_add(10 ** 18, unsafe_div(health_limit, 2)), unsafe_sub(10 ** 18, frac)), unsafe_add(10 ** 18, health_limit))
        f_remove = unsafe_div(unsafe_mul(unsafe_add(f_remove, frac), frac), 10 ** 18)

    return f_remove


@internal
def _liquidate(user: address, min_x: uint256, health_limit: uint256, frac: uint256, callbacker: address, calldata: Bytes[10**4]):
    """
    @notice Perform a bad liquidation of user if the health is too bad
    @param user Address of the user
    @param min_x Minimal amount of stablecoin withdrawn (to avoid liquidators being sandwiched)
    @param health_limit Minimal health to liquidate at
    @param frac Fraction to liquidate; 100% = 10**18
    @param callbacker Address of the callback contract
    @param calldata Any data for callbacker
    """
    debt: uint256 = 0
    rate_mul: uint256 = 0
    debt, rate_mul = self._debt(user)

    if health_limit != 0:
        assert self._health(user, debt, True, health_limit) < 0, "Not enough rekt"

    final_debt: uint256 = debt
    debt = unsafe_div(debt * frac + (10**18 - 1), 10**18)
    assert debt > 0
    final_debt = unsafe_sub(final_debt, debt)

    # Withdraw sender's stablecoin and collateral to our contract
    # When frac is set - we withdraw a bit less for the same debt fraction
    # f_remove = ((1 + h/2) / (1 + h) * (1 - frac) + frac) * frac
    # where h is health limit.
    # This is less than full h discount but more than no discount
    xy: uint256[2] = extcall AMM.withdraw(user, self._get_f_remove(frac, health_limit))  # [stable, collateral]

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
            cb: CallbackData = self.execute_callback(
                callbacker, CALLBACK_LIQUIDATE, user, xy[0], xy[1], debt, calldata)
            assert cb.stablecoins >= to_repay, "not enough proceeds"
            if cb.stablecoins > to_repay:
                self.transferFrom(BORROWED_TOKEN, callbacker, msg.sender, unsafe_sub(cb.stablecoins, to_repay))
            self.transferFrom(BORROWED_TOKEN, callbacker, self, to_repay)
            self.transferFrom(COLLATERAL_TOKEN, callbacker, msg.sender, cb.collateral)

    else:
        # Withdraw collateral
        self.transferFrom(COLLATERAL_TOKEN, AMM.address, msg.sender, xy[1])
        # Return what's left to user
        if xy[0] > debt:
            self.transferFrom(BORROWED_TOKEN, AMM.address, msg.sender, unsafe_sub(xy[0], debt))

    self.redeemed += debt
    self.loan[user] = Loan(initial_debt=final_debt, rate_mul=rate_mul)
    log Repay(user=user, collateral_decrease=xy[1], loan_decrease=debt)
    log Liquidate(liquidator=msg.sender, user=user, collateral_received=xy[1], stablecoin_received=xy[0], debt=debt)
    if final_debt == 0:
        log UserState(user=user, collateral=0, debt=0, n1=0, n2=0, liquidation_discount=0)  # Not logging partial removeal b/c we have not enough info
        self._remove_from_list(user)

    d: uint256 = self._total_debt.initial_debt * rate_mul // self._total_debt.rate_mul
    self._total_debt.initial_debt = unsafe_sub(max(d, debt), debt)
    self._total_debt.rate_mul = rate_mul

    self._save_rate()


@external
@nonreentrant
def liquidate(user: address, min_x: uint256, frac: uint256 = 10**18, callbacker: address = empty(address), calldata: Bytes[10**4] = b""):
    """
    @notice Perform a bad liquidation (or self-liquidation) of user if health is not good
    @param min_x Minimal amount of stablecoin to receive (to avoid liquidators being sandwiched)
    @param frac Fraction to liquidate; 100% = 10**18
    @param callbacker Address of the callback contract
    @param calldata Any data for callbacker
    """
    discount: uint256 = 0
    if not self._check_approval(user):
        discount = self.liquidation_discounts[user]
    self._liquidate(user, min_x, discount, min(frac, 10**18), callbacker, calldata)


@view
@external
@nonreentrant
def tokens_to_liquidate(user: address, frac: uint256 = 10 ** 18) -> uint256:
    """
    @notice Calculate the amount of stablecoins to have in liquidator's wallet to liquidate a user
    @param user Address of the user to liquidate
    @param frac Fraction to liquidate; 100% = 10**18
    @return The amount of stablecoins needed
    """
    health_limit: uint256 = 0
    if not self._check_approval(user):
        health_limit = self.liquidation_discounts[user]
    stablecoins: uint256 = unsafe_div((staticcall AMM.get_sum_xy(user))[0] * self._get_f_remove(frac, health_limit), 10 ** 18)
    debt: uint256 = unsafe_div(self._debt(user)[0] * frac, 10 ** 18)

    return unsafe_sub(max(debt, stablecoins), stablecoins)


@view
@external
@nonreentrant
def health(user: address, full: bool = False) -> int256:
    """
    @notice Returns position health normalized to 1e18 for the user.
            Liquidation starts when < 0, however devaluation of collateral doesn't cause liquidation
    """
    return self._health(user, self._debt(user)[0], full, self.liquidation_discounts[user])


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
    n_loans: uint256 = self.n_loans
    limit: uint256 = _limit
    if _limit == 0:
        limit = n_loans
    ix: uint256 = _from
    out: DynArray[Position, 1000] = []
    for i: uint256 in range(10**6):
        if ix >= n_loans or i == limit:
            break
        user: address = self.loans[ix]
        debt: uint256 = self._debt(user)[0]
        health: int256 = self._health(user, debt, True, self.liquidation_discounts[user])
        if health < 0:
            xy: uint256[2] = staticcall AMM.get_sum_xy(user)
            out.append(Position(
                user=user,
                x=xy[0],
                y=xy[1],
                debt=debt,
                health=health
            ))
        ix += 1
    return out


# AMM has a nonreentrant decorator
@view
@external
def amm_price() -> uint256:
    """
    @notice Current price from the AMM
    """
    return staticcall AMM.get_p()


@view
@external
@nonreentrant
def user_prices(user: address) -> uint256[2]:  # Upper, lower
    """
    @notice Lowest price of the lower band and highest price of the upper band the user has deposit in the AMM
    @param user User address
    @return (upper_price, lower_price)
    """
    assert staticcall AMM.has_liquidity(user)
    ns: int256[2] = staticcall AMM.read_user_tick_numbers(user) # ns[1] > ns[0]
    return [staticcall AMM.p_oracle_up(ns[0]), staticcall AMM.p_oracle_down(ns[1])]


@view
@external
@nonreentrant
def user_state(user: address) -> uint256[4]:
    """
    @notice Return the user state in one call
    @param user User to return the state for
    @return (collateral, stablecoin, debt, N)
    """
    xy: uint256[2] = staticcall AMM.get_sum_xy(user)
    ns: int256[2] = staticcall AMM.read_user_tick_numbers(user) # ns[1] > ns[0]
    return [xy[1], xy[0], self._debt(user)[0], convert(unsafe_add(unsafe_sub(ns[1], ns[0]), 1), uint256)]


# AMM has nonreentrant decorator
@external
def set_amm_fee(fee: uint256):
    """
    @notice Set the AMM fee (factory admin only)
    @param fee The fee which should be no higher than MAX_FEE
    """
    assert msg.sender == staticcall FACTORY.admin()
    assert fee <= MAX_AMM_FEE and fee >= MIN_AMM_FEE, "Fee"
    extcall AMM.set_fee(fee)


@nonreentrant
@external
def set_monetary_policy(monetary_policy: address):
    """
    @notice Set monetary policy contract
    @param monetary_policy Address of the monetary policy contract
    """
    assert msg.sender == staticcall FACTORY.admin()
    self.monetary_policy = MonetaryPolicy(monetary_policy)
    extcall MonetaryPolicy(monetary_policy).rate_write()
    log SetMonetaryPolicy(monetary_policy=monetary_policy)


@nonreentrant
@external
def set_borrowing_discounts(loan_discount: uint256, liquidation_discount: uint256):
    """
    @notice Set discounts at which we can borrow (defines max LTV) and where bad liquidation starts
    @param loan_discount Discount which defines LTV
    @param liquidation_discount Discount where bad liquidation starts
    """
    assert msg.sender == staticcall FACTORY.admin()
    assert loan_discount > liquidation_discount
    assert liquidation_discount >= MIN_LIQUIDATION_DISCOUNT
    assert loan_discount <= MAX_LOAN_DISCOUNT
    self.liquidation_discount = liquidation_discount
    self.loan_discount = loan_discount
    log SetBorrowingDiscounts(loan_discount=loan_discount, liquidation_discount=liquidation_discount)


@external
@nonreentrant
def set_callback(cb: address):
    """
    @notice Set liquidity mining callback
    """
    assert msg.sender == staticcall FACTORY.admin()
    extcall AMM.set_callback(cb)
    log SetLMCallback(callback=cb)


@external
@view
def admin_fees() -> uint256:
    """
    @notice Calculate the amount of fees obtained from the interest
    """
    minted: uint256 = self.minted
    return unsafe_sub(max(self._get_total_debt() + self.redeemed, minted), minted)


@external
@nonreentrant
def collect_fees() -> uint256:
    """
    @notice Collect the fees charged as interest.
    """
    _to: address = staticcall FACTORY.fee_receiver()

    # Borrowing-based fees
    rate_mul: uint256 = staticcall AMM.get_rate_mul()
    loan: Loan = self._total_debt
    loan.initial_debt = loan.initial_debt * rate_mul // loan.rate_mul
    loan.rate_mul = rate_mul
    self._total_debt = loan

    self._save_rate()

    # Amount which would have been redeemed if all the debt was repaid now
    to_be_redeemed: uint256 = loan.initial_debt + self.redeemed
    # Amount which was minted when borrowing + all previously claimed admin fees
    minted: uint256 = self.minted
    # Difference between to_be_redeemed and minted amount is exactly due to interest charged
    if to_be_redeemed > minted:
        self.minted = to_be_redeemed
        to_be_redeemed = unsafe_sub(to_be_redeemed, minted)  # Now this is the fees to charge
        self.transfer(BORROWED_TOKEN, _to, to_be_redeemed)
        log CollectFees(amount=to_be_redeemed, new_supply=loan.initial_debt)
        return to_be_redeemed
    else:
        log CollectFees(amount=0, new_supply=loan.initial_debt)
        return 0


# Allowance methods

@external
def approve(_spender: address, _allow: bool):
    """
    @notice Allow another address to borrow and repay for the user
    @param _spender Address to whitelist for the action
    @param _allow Whether to turn the approval on or off (no amounts)
    """
    self.approval[msg.sender][_spender] = _allow
    log Approval(owner=msg.sender, spender=_spender, allow=_allow)


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
    log SetExtraHealth(user=msg.sender, health=_value)
