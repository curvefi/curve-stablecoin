# @version 0.3.7

interface LLAMMA:
    def A() -> uint256: view
    def get_p() -> uint256: view
    def active_band() -> int256: view
    def p_oracle_up(n: int256) -> uint256: view
    def p_oracle_down(n: int256) -> uint256: view
    def deposit_range(user: address, amount: uint256, n1: int256, n2: int256, move_coins: bool): nonpayable
    def read_user_tick_numbers(_for: address) -> int256[2]: view
    def get_sum_xy(user: address) -> uint256[2]: view
    def withdraw(user: address, move_to: address) -> uint256[2]: nonpayable
    def get_x_down(user: address) -> uint256: view
    def get_y_up(user: address) -> uint256: view
    def get_rate_mul() -> uint256: view
    def set_rate(rate: uint256) -> uint256: nonpayable
    def set_fee(fee: uint256): nonpayable
    def set_admin_fee(fee: uint256): nonpayable
    def price_oracle() -> uint256: view
    def can_skip_bands(n_end: int256) -> bool: view
    def bands_x(n: int256) -> uint256: view
    def set_price_oracle(price_oracle: PriceOracle): nonpayable
    def admin_fees_x() -> uint256: view
    def admin_fees_y() -> uint256: view
    def reset_admin_fees(): nonpayable
    def has_liquidity(user: address) -> bool: view

interface ERC20:
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable
    def transfer(_to: address, _value: uint256) -> bool: nonpayable
    def decimals() -> uint256: view
    def approve(_spender: address, _value: uint256) -> bool: nonpayable

interface MonetaryPolicy:
    def rate_write() -> uint256: nonpayable

interface Factory:
    def stablecoin() -> address: view
    def admin() -> address: view
    def fee_receiver() -> address: view

interface PriceOracle:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable


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

event CollectFees:
    amount: uint256
    new_supply: uint256


struct Loan:
    initial_debt: uint256
    rate_mul: uint256


FACTORY: immutable(Factory)
STABLECOIN: immutable(ERC20)
MAX_LOAN_DISCOUNT: constant(uint256) = 5 * 10**17
MIN_LIQUIDATION_DISCOUNT: constant(uint256) = 10**16 # Start liquidating when threshold reached
MAX_TICKS: constant(int256) = 50
MAX_TICKS_UINT: constant(uint256) = 50
MIN_TICKS: constant(int256) = 5
MAX_SKIP_TICKS: constant(uint256) = 1024

MAX_RATE: constant(uint256) = 43959106799  # 400% APY

loans: HashMap[address, Loan]
liquidation_discounts: public(HashMap[address, uint256])
_total_debt: Loan

minted: public(uint256)
redeemed: public(uint256)

monetary_policy: public(MonetaryPolicy)
liquidation_discount: public(uint256)
loan_discount: public(uint256)

COLLATERAL_TOKEN: immutable(ERC20)
COLLATERAL_PRECISION: immutable(uint256)

AMM: immutable(LLAMMA)
A: immutable(uint256)
Aminus1: immutable(uint256)
LOG2_A_RATIO: immutable(int256)  # log(A / (A - 1))
SQRT_BAND_RATIO: immutable(uint256)

MAX_ADMIN_FEE: constant(uint256) = 10**18  # 100%
MAX_FEE: constant(uint256) = 10**17  # 10%


@external
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
    stablecoin: ERC20 = ERC20(Factory(msg.sender).stablecoin())
    STABLECOIN = stablecoin
    assert stablecoin.decimals() == 18

    self.monetary_policy = MonetaryPolicy(monetary_policy)

    self.liquidation_discount = liquidation_discount
    self.loan_discount = loan_discount
    self._total_debt.rate_mul = 10**18

    AMM = LLAMMA(amm)
    _A: uint256 = LLAMMA(amm).A()
    A = _A
    Aminus1 = _A - 1
    LOG2_A_RATIO = self.log2(_A * 10**18 / (_A - 1))

    COLLATERAL_TOKEN = ERC20(collateral_token)
    COLLATERAL_PRECISION = 10 ** (18 - ERC20(collateral_token).decimals())

    SQRT_BAND_RATIO = isqrt(10**36 * _A / (_A - 1))

    stablecoin.approve(msg.sender, max_value(uint256))


@internal
@pure
def log2(_x: uint256) -> int256:
    """
    @notice int(1e18 * log2(_x / 1e18))
    """
    # adapted from: https://medium.com/coinmonks/9aef8515136e
    # and vyper log implementation
    # Might use more optimal solmate's log
    inverse: bool = _x < 10**18
    res: uint256 = 0
    x: uint256 = _x
    if inverse:
        x = 10**36 / x
    t: uint256 = 2**7
    for i in range(8):
        p: uint256 = pow_mod256(2, t)
        if x >= unsafe_mul(p, 10**18):
            x = unsafe_div(x, p)
            res = unsafe_add(unsafe_mul(t, 10**18), res)
        t = unsafe_div(t, 2)
    d: uint256 = 10**18
    for i in range(34):  # 10 decimals: math.log(10**10, 2) == 33.2. Need more?
        if (x >= 2 * 10**18):
            res = unsafe_add(res, d)
            x = unsafe_div(x, 2)
        x = unsafe_div(unsafe_mul(x, x), 10**18)
        d = unsafe_div(d, 2)
    if inverse:
        return -convert(res, int256)
    else:
        return convert(res, int256)


@external
@view
def factory() -> Factory:
    """
    @notice Address of the factory
    """
    return FACTORY


@external
@view
def amm() -> LLAMMA:
    """
    @notice Address of the AMM
    """
    return AMM


@external
@view
def collateral_token() -> ERC20:
    """
    @notice Address of the collateral token
    """
    return COLLATERAL_TOKEN


@internal
def _rate_mul_w() -> uint256:
    """
    @notice Getter for rate_mul (the one which is 1.0+) from the AMM
    """
    rate: uint256 = min(self.monetary_policy.rate_write(), MAX_RATE)
    return AMM.set_rate(rate)


@internal
def _debt(user: address) -> (uint256, uint256):
    """
    @notice Get the value of debt and rate_mul and update the rate_mul counter
    @param user User address
    @return (debt, rate_mul)
    """
    rate_mul: uint256 = self._rate_mul_w()
    loan: Loan = self.loans[user]
    if loan.initial_debt == 0:
        return (0, rate_mul)
    else:
        return (loan.initial_debt * rate_mul / loan.rate_mul, rate_mul)


@internal
@view
def _debt_ro(user: address) -> uint256:
    """
    @notice Get the value of debt without changing the state
    @param user User address
    @return Value of debt
    """
    rate_mul: uint256 = AMM.get_rate_mul()
    loan: Loan = self.loans[user]
    if loan.initial_debt == 0:
        return 0
    else:
        return loan.initial_debt * rate_mul / loan.rate_mul


@external
@view
def debt(user: address) -> uint256:
    """
    @notice Get the value of debt without changing the state
    @param user User address
    @return Value of debt
    """
    return self._debt_ro(user)


@external
@view
def loan_exists(user: address) -> bool:
    """
    @notice Check whether there is a loan of `user` in existence
    """
    return self.loans[user].initial_debt > 0


@external
@view
def total_debt() -> uint256:
    """
    @notice Total debt of this controller
    """
    rate_mul: uint256 = AMM.get_rate_mul()
    loan: Loan = self._total_debt
    return loan.initial_debt * rate_mul / loan.rate_mul


@internal
@view
def get_y_effective(collateral: uint256, N: uint256, discount: uint256) -> uint256:
    """
    @notice Intermediary method which calculates y_effective defined as x_effective * p_base,
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
    d_y_effective: uint256 = collateral * (10**18 - discount) / (SQRT_BAND_RATIO * N)
    y_effective: uint256 = d_y_effective
    for i in range(1, MAX_TICKS_UINT):
        if i == N:
            break
        d_y_effective = unsafe_div(d_y_effective * Aminus1, A)
        y_effective = unsafe_add(y_effective, d_y_effective)
    return y_effective


@internal
@view
def _calculate_debt_n1(collateral: uint256, debt: uint256, N: uint256) -> int256:
    """
    @notice Calculate the upper band number for the deposit to sit in to support
            the given debt. Reverts if requested debt is too high.
    @param collateral Amount of collateral (at its native precision)
    @param debt Amount of requested debt
    @param N Number of bands to deposit into
    @return Upper band n1 (n1 <= n2) to deposit into. Signed integer
    """
    assert debt > 0, "No loan"
    n0: int256 = AMM.active_band()
    p_base: uint256 = AMM.p_oracle_up(n0)

    # x_effective = y / N * p_oracle_up(n1) * sqrt((A - 1) / A) * sum_{0..N-1}(((A-1) / A)**k)
    # === d_y_effective * p_oracle_up(n1) * sum(...) === y_effective * p_oracle_up(n1)
    # d_y_effective = y / N / sqrt(A / (A - 1))
    y_effective: uint256 = self.get_y_effective(collateral * COLLATERAL_PRECISION, N, self.loan_discount)
    # p_oracle_up(n1) = base_price * ((A - 1) / A)**n1

    # We borrow up until min band touches p_oracle,
    # or it touches non-empty bands which cannot be skipped.
    # We calculate required n1 for given (collateral, debt),
    # and if n1 corresponds to price_oracle being too high, or unreachable band
    # - we revert.

    # n1 is band number based on adiabatic trading, e.g. when p_oracle ~ p
    y_effective = y_effective * p_base / (debt + 1)  # Now it's a ratio

    # n1 = floor(log2(y_effective) / self.logAratio)
    # EVM semantics is not doing floor unlike Python, so we do this
    assert y_effective > 0, "Amount too low"
    n1: int256 = self.log2(y_effective)  # <- switch to faster ln() XXX?
    if n1 < 0:
        n1 -= LOG2_A_RATIO - 1
    n1 /= LOG2_A_RATIO

    n1 = min(n1, 1024 - convert(N, int256)) + n0
    if n1 <= n0:
        assert AMM.can_skip_bands(n1 - 1), "Debt too high"

    # Let's not rely on active_band corresponding to price_oracle:
    # this will be not correct if we are in the area of empty bands
    assert AMM.p_oracle_up(n1) < AMM.price_oracle(), "Debt too high"

    return n1


@internal
@view
def max_p_base() -> uint256:
    """
    @notice Calculate max base price including skipping bands
    """
    n1: int256 = AMM.active_band() + 5  # Should be correct unless price changes suddenly by 5+ bands
    p_base: uint256 = AMM.p_oracle_up(n1)
    p_oracle: uint256 = AMM.price_oracle()

    for i in range(MAX_SKIP_TICKS + 1):
        n1 -= 1
        if AMM.bands_x(n1) != 0:
            break
        p_base_prev: uint256 = p_base
        p_base = unsafe_div(p_base * A, Aminus1)
        if p_base > p_oracle:
            return p_base_prev

    return p_base


@external
@view
def max_borrowable(collateral: uint256, N: uint256) -> uint256:
    """
    @notice Calculation of maximum which can be borrowed (details in comments)
    @param collateral Collateral amount against which to borrow
    @param N number of bands to have the deposit into
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

    y_effective: uint256 = self.get_y_effective(collateral * COLLATERAL_PRECISION, N, self.loan_discount)

    x: uint256 = max(y_effective * self.max_p_base() / 10**18, 1) - 1
    return unsafe_div(x * (10**18 - 10**14), 10**18)  # Make it a bit smaller


@external
@view
def min_collateral(debt: uint256, N: uint256) -> uint256:
    """
    @notice Minimal amount of collateral required to support debt
    @param debt The debt to support
    @param N Number of bands to deposit into
    @return Minimal collateral required
    """
    # Add N**2 to account for precision loss in multiple bands, e.g. N * 1 / (y/N) = N**2 / y
    return (debt * 10**18 / self.max_p_base() * 10**18 / self.get_y_effective(10**18, N, self.loan_discount) + N**2) / COLLATERAL_PRECISION * 10**18 / (10**18 - 10**14)


@external
@view
def calculate_debt_n1(collateral: uint256, debt: uint256, N: uint256) -> int256:
    """
    @notice Calculate the upper band number for the deposit to sit in to support
            the given debt. Reverts if requested debt is too high.
    @param collateral Amount of collateral (at its native precision)
    @param debt Amount of requested debt
    @param N Number of bands to deposit into
    @return Upper band n1 (n1 <= n2) to deposit into. Signed integer
    """
    return self._calculate_debt_n1(collateral, debt, N)


@external
@nonreentrant('lock')
def create_loan(collateral: uint256, debt: uint256, N: uint256):
    """
    @notice Create loan
    @param collateral Amount of collateral to use
    @param debt Stablecoin debt to take
    @param N Number of bands to deposit into (to do autoliquidation-deliquidation),
           can be from MIN_TICKS to MAX_TICKS
    """
    assert self.loans[msg.sender].initial_debt == 0, "Loan already created"
    assert N > MIN_TICKS-1, "Need more ticks"
    assert N < MAX_TICKS+1, "Need less ticks"

    n1: int256 = self._calculate_debt_n1(collateral, debt, N)
    n2: int256 = n1 + convert(N - 1, int256)

    rate_mul: uint256 = self._rate_mul_w()
    self.loans[msg.sender] = Loan({initial_debt: debt, rate_mul: rate_mul})
    liquidation_discount: uint256 = self.liquidation_discount
    self.liquidation_discounts[msg.sender] = liquidation_discount
    total_debt: uint256 = self._total_debt.initial_debt * rate_mul / self._total_debt.rate_mul + debt
    self._total_debt.initial_debt = total_debt
    self._total_debt.rate_mul = rate_mul

    AMM.deposit_range(msg.sender, collateral, n1, n2, False)
    assert COLLATERAL_TOKEN.transferFrom(msg.sender, AMM.address, collateral, default_return_value=True)

    STABLECOIN.transfer(msg.sender, debt)
    self.minted += debt

    log UserState(msg.sender, collateral, debt, n1, n2, liquidation_discount)
    log Borrow(msg.sender, collateral, debt)


@internal
def _add_collateral_borrow(d_collateral: uint256, d_debt: uint256, _for: address, remove_collateral: bool):
    """
    @notice Internal method to borrow and add or remove collateral
    @param d_collateral Amount of collateral to add
    @param d_debt Amount of debt increase
    @param _for Address to transfer tokens to
    @param remove_collateral Remove collateral instead of adding
    """
    debt: uint256 = 0
    rate_mul: uint256 = 0
    debt, rate_mul = self._debt(_for)
    assert debt > 0, "Loan doesn't exist"
    debt += d_debt
    ns: int256[2] = AMM.read_user_tick_numbers(_for)
    size: uint256 = convert(ns[1] - ns[0] + 1, uint256)

    xy: uint256[2] = AMM.withdraw(_for, empty(address))
    assert xy[0] == 0, "Already in underwater mode"
    if remove_collateral:
        xy[1] -= d_collateral
    else:
        xy[1] += d_collateral
    n1: int256 = self._calculate_debt_n1(xy[1], debt, size)
    n2: int256 = n1 + ns[1] - ns[0]

    AMM.deposit_range(_for, xy[1], n1, n2, False)
    self.loans[_for] = Loan({initial_debt: debt, rate_mul: rate_mul})
    liquidation_discount: uint256 = self.liquidation_discount
    self.liquidation_discounts[_for] = liquidation_discount

    if d_debt != 0:
        total_debt: uint256 = self._total_debt.initial_debt * rate_mul / self._total_debt.rate_mul + d_debt
        self._total_debt.initial_debt = total_debt
        self._total_debt.rate_mul = rate_mul

    if remove_collateral:
        log RemoveCollateral(_for, d_collateral)
    else:
        log Borrow(_for, d_collateral, d_debt)
    log UserState(_for, xy[1], debt, n1, n2, liquidation_discount)


@external
@nonreentrant('lock')
def add_collateral(collateral: uint256, _for: address = msg.sender):
    """
    @notice Add extra collateral to avoid bad liqidations
    @param collateral Amount of collateral to add
    @param _for Address to add collateral for
    """
    if collateral == 0:
        return
    self._add_collateral_borrow(collateral, 0, _for, False)
    assert COLLATERAL_TOKEN.transferFrom(msg.sender, AMM.address, collateral, default_return_value=True)


@external
@nonreentrant('lock')
def remove_collateral(collateral: uint256):
    """
    @notice Remove some collateral without repaying the debt
    @param collateral Amount of collateral to remove
    """
    if collateral == 0:
        return
    self._add_collateral_borrow(collateral, 0, msg.sender, True)
    assert COLLATERAL_TOKEN.transferFrom(AMM.address, msg.sender, collateral, default_return_value=True)


@external
@nonreentrant('lock')
def borrow_more(collateral: uint256, debt: uint256):
    """
    @notice Borrow more stablecoins while adding more collateral (not necessary)
    @param collateral Amount of collateral to add
    @param debt Amount of stablecoin debt to take
    """
    if debt == 0:
        return
    self._add_collateral_borrow(collateral, debt, msg.sender, False)
    if collateral != 0:
        assert COLLATERAL_TOKEN.transferFrom(msg.sender, AMM.address, collateral, default_return_value=True)
    STABLECOIN.transfer(msg.sender, debt)
    self.minted += debt


@external
@nonreentrant('lock')
def repay(_d_debt: uint256, _for: address):
    """
    @notice Repay debt (partially or fully)
    @param _d_debt The amount of debt to repay. If higher than the current debt - will do full repayment
    @param _for The user to repay the debt for
    """
    if _d_debt == 0:
        return
    # Or repay all for MAX_UINT256
    # Withdraw if debt become 0
    debt: uint256 = 0
    rate_mul: uint256 = 0
    debt, rate_mul = self._debt(_for)
    assert debt > 0, "Loan doesn't exist"
    d_debt: uint256 = min(debt, _d_debt)
    debt -= d_debt

    ns: int256[2] = AMM.read_user_tick_numbers(_for)
    size: uint256 = convert(ns[1] - ns[0] + 1, uint256)

    if debt == 0:
        # Allow to withdraw all assets even when underwater
        xy: uint256[2] = AMM.withdraw(_for, _for)
        log UserState(_for, 0, 0, 0, 0, 0)
        log Repay(_for, xy[1], d_debt)

    else:
        active_band: int256 = AMM.active_band()
        for i in range(MAX_SKIP_TICKS):
            if AMM.bands_x(active_band) != 0:
                break
            active_band -= 1

        if ns[0] > active_band:
            # Not in liquidation - can move bands
            xy: uint256[2] = AMM.withdraw(_for, empty(address))
            n1: int256 = self._calculate_debt_n1(xy[1], debt, size)
            n2: int256 = n1 + ns[1] - ns[0]
            AMM.deposit_range(_for, xy[1], n1, n2, False)
            liquidation_discount: uint256 = self.liquidation_discount
            self.liquidation_discounts[_for] = liquidation_discount
            log UserState(_for, xy[1], debt, n1, n2, liquidation_discount)
            log Repay(_for, 0, d_debt)
        else:
            # Underwater - cannot move band but can avoid a bad liquidation
            log UserState(_for, max_value(uint256), debt, ns[0], ns[1], self.liquidation_discounts[_for])
            log Repay(_for, 0, d_debt)

    # If we withdrew already - will burn less!
    STABLECOIN.transferFrom(msg.sender, self, d_debt)  # fail: insufficient funds
    self.redeemed += d_debt

    self.loans[_for] = Loan({initial_debt: debt, rate_mul: rate_mul})
    total_debt: uint256 = self._total_debt.initial_debt * rate_mul / self._total_debt.rate_mul
    self._total_debt.initial_debt = max(total_debt, d_debt) - d_debt
    self._total_debt.rate_mul = rate_mul


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
    _debt: int256 = convert(debt, int256)
    assert debt > 0, "Loan doesn't exist"
    xmax: int256 = convert(AMM.get_x_down(user), int256)
    health: int256 = 10**18
    if liquidation_discount > 0:
        health -= convert(liquidation_discount, int256)
    health = xmax * health / _debt - 10**18

    if full:
        active_band: int256 = AMM.active_band()
        ns: int256[2] = AMM.read_user_tick_numbers(user) # ns[1] > ns[0]
        if ns[0] > active_band:  # We are not in liquidation mode
            p: uint256 = AMM.price_oracle()
            p_up: uint256 = AMM.p_oracle_up(ns[0])
            if p > p_up:
                health += convert((p - p_up) * AMM.get_sum_xy(user)[1] * COLLATERAL_PRECISION / debt, int256)

    return health


@external
@view
def health_calculator(user: address, d_collateral: int256, d_debt: int256, full: bool) -> int256:
    """
    @notice Health predictor in case user changes the debt or collateral
    @param user Address of the user
    @param d_collateral Change in collateral amount (signed)
    @param d_debt Change in debt amount (signed)
    @param full Whether it's a 'full' health or not
    @return Signed health value
    """
    xy: uint256[2] = AMM.get_sum_xy(user)
    xy[1] *= COLLATERAL_PRECISION
    ns: int256[2] = AMM.read_user_tick_numbers(user)
    N: uint256 = convert(ns[1] - ns[0] + 1, uint256)

    n1: int256 = 0
    collateral: int256 = 0
    x_eff: int256 = 0
    debt: int256 = convert(self._debt_ro(user), int256) + d_debt
    if debt <= 0:
        return max_value(int256)

    active_band: int256 = AMM.active_band()
    for i in range(MAX_SKIP_TICKS):
        if AMM.bands_x(active_band) != 0:
            break
        active_band -= 1

    if ns[0] > active_band:  # re-deposit
        collateral = convert(xy[1], int256) + d_collateral
        n1 = self._calculate_debt_n1(xy[1], convert(debt, uint256), N)

    else:
        n1 = ns[0]
        x_eff = convert(AMM.get_x_down(user) * 10**18, int256)

    p0: int256 = convert(AMM.p_oracle_up(n1), int256)
    if ns[0] > active_band:
        x_eff = convert(self.get_y_effective(convert(collateral, uint256), N, 0), int256) * p0
    ld: int256 = convert(self.liquidation_discounts[user], int256)

    health: int256 = x_eff / debt
    health = health - health * ld / 10**18 - 10**18

    if full:
        if n1 > active_band:  # We are not in liquidation mode
            p_diff: int256 = max(p0, convert(AMM.price_oracle(), int256)) - p0
            if p_diff > 0:
                health += p_diff * collateral / debt

    return health


@internal
def _liquidate(user: address, min_x: uint256, health_limit: uint256):
    """
    @notice Perform a bad liquidation of user if the health is too bad
    @param user Address of the user
    @param min_x Minimal amount of stablecoin to receive (to avoid liquidators being sandwiched)
    @param health_limit Minimal health to liquidate at
    """
    debt: uint256 = 0
    rate_mul: uint256 = 0
    debt, rate_mul = self._debt(user)

    if health_limit != 0:
        assert self._health(user, debt, True, health_limit) < 0, "Not enough rekt"

    # Send all the sender's stablecoin and collateral to our contract
    xy: uint256[2] = AMM.withdraw(user, empty(address))  # [stable, collateral]

    # x increase in same block -> price up -> good
    # x decrease in same block -> price down -> bad
    assert xy[0] >= min_x, "Sandwich"

    min_amm_burn: uint256 = min(xy[0], debt)
    if min_amm_burn != 0:
        STABLECOIN.transferFrom(AMM.address, self, min_amm_burn)
        self.redeemed += min_amm_burn

    if debt > xy[0]:
        # Request what's left from user
        to_transfer: uint256 = debt - xy[0]
        STABLECOIN.transferFrom(msg.sender, self, to_transfer)
        self.redeemed += to_transfer
    else:
        # Return what's left to user
        to_transfer: uint256 = xy[0] - debt
        STABLECOIN.transferFrom(AMM.address, msg.sender, to_transfer)
        self.redeemed += to_transfer

    assert COLLATERAL_TOKEN.transferFrom(AMM.address, msg.sender, xy[1], default_return_value=True)

    self.loans[user] = Loan({initial_debt: 0, rate_mul: rate_mul})
    log UserState(user, 0, 0, 0, 0, 0)
    log Repay(user, xy[1], debt)
    log Liquidate(msg.sender, user, xy[1], xy[0], debt)

    d: uint256 = self._total_debt.initial_debt * rate_mul / self._total_debt.rate_mul
    self._total_debt.initial_debt = max(d, debt) - debt
    self._total_debt.rate_mul = rate_mul


@external
@nonreentrant('lock')
def liquidate(user: address, min_x: uint256):
    """
    @notice Peform a bad liquidation of user if health is not good
    @param min_x Minimal amount of stablecoin to receive (to avoid liquidators being sandwiched)
    """
    self._liquidate(user, min_x, self.liquidation_discounts[user])


@external
@nonreentrant('lock')
def self_liquidate(min_x: uint256):
    """
    @notice Peform a self-liquidation to avoid a bad liquidation
    @param min_x Minimal amount of stablecoin to receive (to avoid liquidators being sandwiched)
    """
    self._liquidate(msg.sender, min_x, 0)


@view
@external
def tokens_to_liquidate(user: address) -> uint256:
    """
    @notice Calculate the amount of stablecoins to have in liquidator's wallet to liquidate a user
    @param user Address of the user to liquidate
    @return The amount of stablecoins needed
    """
    xy: uint256[2] = AMM.get_sum_xy(user)
    return max(self._debt_ro(user), xy[0]) - xy[0]


@view
@external
def health(user: address, full: bool = False) -> int256:
    """
    @notice Returns position health normalized to 1e18 for the user.
             Liquidation starts when < 0, however devaluation of collateral doesn't cause liquidation
    """
    return self._health(user, self._debt_ro(user), full, self.liquidation_discounts[user])


@view
@external
def amm_price() -> uint256:
    """
    @notice Current price from the AMM
    """
    return AMM.get_p()


@view
@external
def user_prices(user: address) -> uint256[2]:  # Upper, lower
    """
    @notice Lowest price of the lower band and highest price of the upper band the user has deposit in the AMM
    @param user User address
    @return (upper_price, lower_price)
    """
    assert AMM.has_liquidity(user)
    ns: int256[2] = AMM.read_user_tick_numbers(user) # ns[1] > ns[0]
    return [AMM.p_oracle_up(ns[0]), AMM.p_oracle_down(ns[1])]


@view
@external
def user_state(user: address) -> uint256[4]:
    """
    @notice Return the user state in one call
    @param user User to return the state for
    @return (collateral, stablecoin, debt, N)
    """
    xy: uint256[2] = AMM.get_sum_xy(user)
    ns: int256[2] = AMM.read_user_tick_numbers(user) # ns[1] > ns[0]
    return [xy[1], xy[0], self._debt_ro(user), convert(ns[1] - ns[0] + 1, uint256)]


@external
def set_amm_fee(fee: uint256):
    """
    @notice Set the AMM fee (factory admin only)
    @param fee The fee which should be no higher than MAX_FEE
    """
    assert msg.sender == FACTORY.admin()
    assert fee <= MAX_FEE, "High fee"
    AMM.set_fee(fee)


@external
def set_amm_admin_fee(fee: uint256):
    """
    @notice Set AMM's admin fee
    @param fee New admin fee (not higher than MAX_ADMIN_FEE)
    """
    assert msg.sender == FACTORY.admin()
    assert fee <= MAX_ADMIN_FEE, "High fee"
    AMM.set_admin_fee(fee)


@external
def set_amm_price_oracle(price_oracle: PriceOracle):
    """
    @notice Set AMM's external price oracle contract
    @param price_oracle Address of the price oracle contract
    """
    assert msg.sender == FACTORY.admin()
    assert price_oracle.price_w() > 0
    assert price_oracle.price() > 0
    AMM.set_price_oracle(price_oracle)


@external
def set_monetary_policy(monetary_policy: address):
    """
    @notice Set monetary policy contract
    @param monetary_policy Address of the monetary policy contract
    """
    assert msg.sender == FACTORY.admin()
    self.monetary_policy = MonetaryPolicy(monetary_policy)
    MonetaryPolicy(monetary_policy).rate_write()
    log SetMonetaryPolicy(monetary_policy)


@external
def set_borrowing_discounts(loan_discount: uint256, liquidation_discount: uint256):
    """
    @notice Set discounts at which we can borrow (defines max LTV) and where bad liquidation starts
    @param loan_discount Discount which defines LTV
    @param liquidation_discount Discount where bad liquidation starts
    """
    assert msg.sender == FACTORY.admin()
    assert loan_discount > liquidation_discount
    assert liquidation_discount >= MIN_LIQUIDATION_DISCOUNT
    assert loan_discount <= MAX_LOAN_DISCOUNT
    self.liquidation_discount = liquidation_discount
    self.loan_discount = loan_discount
    log SetBorrowingDiscounts(loan_discount, liquidation_discount)


@external
@view
def admin_fees() -> uint256:
    """
    @notice Calculate the amount of fees obtained from the interest
    """
    rate_mul: uint256 = AMM.get_rate_mul()
    loan: Loan = self._total_debt
    loan.initial_debt = loan.initial_debt * rate_mul / loan.rate_mul
    loan.initial_debt += self.redeemed
    minted: uint256 = self.minted
    if loan.initial_debt > minted:
        return loan.initial_debt - minted
    else:
        return 0


@external
@nonreentrant('lock')
def collect_fees() -> uint256:
    """
    @notice Collect the fees charged as interest
    """
    _to: address = FACTORY.fee_receiver()
    # AMM-based fees
    borrowed_fees: uint256 = AMM.admin_fees_x()
    collateral_fees: uint256 = AMM.admin_fees_y()
    if borrowed_fees > 0:
        STABLECOIN.transferFrom(AMM.address, _to, borrowed_fees)
    if collateral_fees > 0:
        assert COLLATERAL_TOKEN.transferFrom(AMM.address, _to, collateral_fees, default_return_value=True)
    AMM.reset_admin_fees()
    # Borrowing-based fees
    rate_mul: uint256 = self._rate_mul_w()
    loan: Loan = self._total_debt
    loan.initial_debt = loan.initial_debt * rate_mul / loan.rate_mul
    redeemed: uint256 = loan.initial_debt + self.redeemed
    minted: uint256 = self.minted
    if redeemed > minted:
        redeemed -= minted
        STABLECOIN.transfer(_to, redeemed)
        self.minted += redeemed
        log CollectFees(redeemed, loan.initial_debt)
        return redeemed
    else:
        log CollectFees(0, loan.initial_debt)
        return 0
