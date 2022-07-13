# @version 0.3.3

interface AMM:
    def A() -> uint256: view
    def get_base_price() -> uint256: view
    def p_base_mul() -> uint256: view
    def get_p() -> uint256: view
    def active_band() -> int256: view
    def p_current_up(n: int256) -> uint256: view
    def p_current_down(n: int256) -> uint256: view
    def p_oracle_up(n: int256) -> uint256: view
    def p_oracle_down(n: int256) -> uint256: view
    def deposit_range(user: address, amount: uint256, n1: int256, n2: int256, move_coins: bool): nonpayable
    def read_user_tick_numbers(_for: address) -> int256[2]: view
    def get_sum_xy(user: address) -> uint256[2]: view
    def withdraw(user: address, move_to: address) -> uint256[2]: nonpayable
    def get_x_down(user: address) -> uint256: view
    def get_y_up(user: address) -> uint256: view
    def get_rate_mul() -> uint256: view
    def rugpull(coin: address, _to: address, val: uint256): nonpayable
    def set_rate(rate: uint256) -> uint256: nonpayable
    def set_fee(fee: uint256): nonpayable
    def set_admin_fee(fee: uint256): nonpayable
    def price_oracle() -> uint256: view
    def sqrt_band_ratio() -> uint256: view
    def collateral_precision() -> uint256: view
    def can_skip_bands(n_end: int256) -> bool: view

interface ERC20:
    def totalSupply() -> uint256: view
    def mint(_to: address, _value: uint256) -> bool: nonpayable
    def burnFrom(_to: address, _value: uint256) -> bool: nonpayable
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable
    def decimals() -> uint256: view

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

event Borrow:
    user: indexed(address)
    collateral_increase: uint256
    loan_increase: uint256

event Repay:
    user: indexed(address)
    collateral_decrease: uint256
    loan_decrease: uint256

event Liquidate:
    liquidator: address
    user: address
    collateral_received: uint256
    stablecoin_received: uint256
    debt: uint256

event SetMonetaryPolicy:
    monetary_policy: address

event SetDebtCeiling:
    debt_ceiling: uint256

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

MAX_RATE: constant(uint256) = 43959106799  # 400% APY

loans: HashMap[address, Loan]
_total_debt: Loan

amm: public(AMM)
collateral_token: public(ERC20)
collateral_precision: uint256
monetary_policy: public(MonetaryPolicy)
liquidation_discount: public(uint256)
loan_discount: public(uint256)
debt_ceiling: public(uint256)

A: uint256
logAratio: uint256  # log(A / (A - 1))


@external
def __init__(factory: address):
    FACTORY = Factory(factory)
    stablecoin: ERC20 = ERC20(Factory(factory).stablecoin())
    STABLECOIN = stablecoin
    assert stablecoin.decimals() == 18


@internal
@pure
def log2(_x: uint256) -> uint256:
    # adapted from: https://medium.com/coinmonks/9aef8515136e
    # and vyper log implementation
    res: uint256 = 0
    x: uint256 = _x
    t: uint256 = 2**7
    for i in range(8):
        p: uint256 = pow_mod256(2, t)
        if x >= unsafe_mul(p, 10**18):
            x = unsafe_div(x, p)  # negative shift
            res = unsafe_add(unsafe_mul(t, 10**18), res)
        t = unsafe_div(t, 2)
    d: uint256 = 10**18
    for i in range(34):  # 10 decimals: math.log(10**10, 2) == 33.2. Need more?
        if (x >= 2 * 10**18):
            res = unsafe_add(res, d)
            x = shift(x, -1)  # x /= 2
        x = unsafe_div(unsafe_mul(x, x), 10**18)
        d = shift(d, -1)  # d /= 2
    return res


@external
def initialize(
    collateral_token: address,
    monetary_policy: address,
    loan_discount: uint256,
    liquidation_discount: uint256,
    amm: address,
    debt_ceiling: uint256):
    assert self.collateral_token == ERC20(ZERO_ADDRESS)

    self.collateral_token = ERC20(collateral_token)
    self.monetary_policy = MonetaryPolicy(monetary_policy)

    self.liquidation_discount = liquidation_discount
    self.loan_discount = loan_discount
    self.debt_ceiling = debt_ceiling
    self._total_debt.rate_mul = 10**18

    self.amm = AMM(amm)
    A: uint256 = AMM(amm).A()
    self.A = A
    self.logAratio = self.log2(A * 10**18 / (A - 1))
    self.collateral_precision = AMM(amm).collateral_precision()


@external
@view
def factory() -> Factory:
    return FACTORY


@internal
def _rate_mul_w(amm: AMM) -> uint256:
    rate: uint256 = min(self.monetary_policy.rate_write(), MAX_RATE)
    return amm.set_rate(rate)


@internal
def _debt(user: address) -> (uint256, uint256):
    rate_mul: uint256 = self._rate_mul_w(self.amm)
    loan: Loan = self.loans[user]
    if loan.initial_debt == 0:
        return (0, rate_mul)
    else:
        return (loan.initial_debt * rate_mul / loan.rate_mul, rate_mul)


@internal
@view
def _debt_ro(user: address) -> uint256:
    rate_mul: uint256 = self.amm.get_rate_mul()
    loan: Loan = self.loans[user]
    if loan.initial_debt == 0:
        return 0
    else:
        return loan.initial_debt * rate_mul / loan.rate_mul


@external
@view
def debt(user: address) -> uint256:
    return self._debt_ro(user)


@external
@view
def loan_exists(user: address) -> bool:
    return self.loans[user].initial_debt > 0


@external
@view
def total_debt() -> uint256:
    rate_mul: uint256 = self.amm.get_rate_mul()
    loan: Loan = self._total_debt
    return loan.initial_debt * rate_mul / loan.rate_mul


@internal
@view
def _calculate_debt_n1(collateral: uint256, debt: uint256, N: uint256) -> int256:
    assert debt > 0, "No loan"
    _debt: uint256 = debt + 1
    _collateral: uint256 = unsafe_mul(collateral, self.collateral_precision)
    amm: AMM = self.amm
    # p0: uint256 = amm.p_current_down(n0)
    n0: int256 = amm.active_band()
    p_base: uint256 = amm.get_base_price() * amm.p_base_mul() / 10**18
    loan_discount: uint256 = 10**18 - self.loan_discount

    # x_effective = y / N * p_oracle_up(n1) * sqrt((A - 1) / A) * sum_{0..N-1}(((A-1) / A)**k)
    # === y_effective * p_oracle_up(n1)
    A: uint256 = self.A
    d_y_effective: uint256 = _collateral * loan_discount / amm.sqrt_band_ratio() / N
    y_effective: uint256 = d_y_effective
    for i in range(1, MAX_TICKS_UINT):
        if i == N:
            break
        # Doing unsafe things while in a cycle
        # It's safe, I swear
        d_y_effective = unsafe_div(unsafe_mul(d_y_effective, unsafe_sub(A, 1)), A)
        y_effective = unsafe_add(y_effective, d_y_effective)
    # p_oracle_up(n1) = base_price * ((A - 1) / A)**n1

    y_effective = y_effective * p_base / _debt  # Now it's a ratio
    n1: int256 = convert(self.log2(y_effective) / self.logAratio, int256)
    n1 = min(n1, 1024 - convert(N, int256)) + n0
    if n1 <= n0:
        assert amm.can_skip_bands(n1 - 1), "Debt too high"
    assert _collateral * loan_discount / 10**18 * amm.p_current_down(n0) / 10**18 >= _debt, "Debt too high"

    return n1


@external
@view
def max_borrowable(collateral: uint256, N: uint256) -> uint256:
    _collateral: uint256 = unsafe_mul(collateral, self.collateral_precision)
    amm: AMM = self.amm
    n0: int256 = amm.active_band()
    p_base: uint256 = amm.get_base_price() * amm.p_base_mul() / 10**18
    loan_discount: uint256 = 10**18 - self.loan_discount
    A: uint256 = self.A

    d_y_effective: uint256 = _collateral * loan_discount / amm.sqrt_band_ratio() / N
    y_effective: uint256 = d_y_effective
    for i in range(1, MAX_TICKS_UINT):
        if i == N:
            break
        d_y_effective = unsafe_div(unsafe_mul(d_y_effective, unsafe_sub(A, 1)), A)
        y_effective = unsafe_add(y_effective, d_y_effective)

    x: uint256 = max(y_effective * p_base * unsafe_sub(A, 1) / unsafe_mul(A, 10**18), 1) - 1
    return unsafe_div(x * (10**18 - 10**14), 10**18)  # Make it a bit smaller


@external
@view
def calculate_debt_n1(collateral: uint256, debt: uint256, N: uint256) -> int256:
    return self._calculate_debt_n1(collateral, debt, N)


@external
@nonreentrant('lock')
def create_loan(collateral: uint256, debt: uint256, n: uint256):
    assert self.loans[msg.sender].initial_debt == 0, "Loan already created"
    assert n > MIN_TICKS-1, "Need more ticks"
    assert n < MAX_TICKS+1, "Need less ticks"
    amm: AMM = self.amm

    n1: int256 = self._calculate_debt_n1(collateral, debt, n)
    n2: int256 = n1 + convert(n - 1, int256)

    rate_mul: uint256 = self._rate_mul_w(amm)
    self.loans[msg.sender] = Loan({initial_debt: debt, rate_mul: rate_mul})
    total_debt: uint256 = self._total_debt.initial_debt * rate_mul / self._total_debt.rate_mul + debt
    assert total_debt <= self.debt_ceiling, "Debt ceiling"
    self._total_debt.initial_debt = total_debt
    self._total_debt.rate_mul = rate_mul

    amm.deposit_range(msg.sender, collateral, n1, n2, False)
    self.collateral_token.transferFrom(msg.sender, amm.address, collateral)
    STABLECOIN.mint(msg.sender, debt)

    log UserState(msg.sender, collateral, debt, n1, n2)
    log Borrow(msg.sender, collateral, debt)


@internal
def _add_collateral_borrow(d_collateral: uint256, d_debt: uint256, _for: address):
    debt: uint256 = 0
    rate_mul: uint256 = 0
    debt, rate_mul = self._debt(_for)
    assert debt > 0, "Loan doesn't exist"
    debt += d_debt
    amm: AMM = self.amm
    ns: int256[2] = amm.read_user_tick_numbers(_for)
    size: uint256 = convert(ns[1] - ns[0], uint256)

    xy: uint256[2] = amm.withdraw(_for, ZERO_ADDRESS)
    assert xy[0] == 0, "Already in underwater mode"
    xy[1] += d_collateral
    n1: int256 = self._calculate_debt_n1(xy[1], debt, size)
    assert n1 > amm.active_band(), "Not enough collateral"
    n2: int256 = n1 + ns[1] - ns[0]

    amm.deposit_range(_for, xy[1], n1, n2, False)
    self.loans[_for] = Loan({initial_debt: debt, rate_mul: rate_mul})

    if d_debt != 0:
        total_debt: uint256 = self._total_debt.initial_debt * rate_mul / self._total_debt.rate_mul + d_debt
        assert total_debt <= self.debt_ceiling, "Debt ceiling"
        self._total_debt.initial_debt = total_debt
        self._total_debt.rate_mul = rate_mul

    log Borrow(_for, d_collateral, d_debt)
    log UserState(_for, xy[1], debt, n1, n2)


@external
@nonreentrant('lock')
def add_collateral(collateral: uint256, _for: address):
    self._add_collateral_borrow(collateral, 0, _for)
    self.collateral_token.transferFrom(msg.sender, self.amm.address, collateral)


@external
@nonreentrant('lock')
def borrow_more(collateral: uint256, debt: uint256):
    self._add_collateral_borrow(collateral, debt, msg.sender)
    if collateral != 0:
        self.collateral_token.transferFrom(msg.sender, self.amm.address, collateral)
    STABLECOIN.mint(msg.sender, debt)


@external
@nonreentrant('lock')
def repay(_d_debt: uint256, _for: address):
    # Or repay all for MAX_UINT256
    # Withdraw if debt become 0
    debt: uint256 = 0
    rate_mul: uint256 = 0
    debt, rate_mul = self._debt(_for)
    assert debt > 0, "Loan doesn't exist"
    d_debt: uint256 = min(debt, _d_debt)
    debt -= d_debt

    amm: AMM = self.amm
    ns: int256[2] = amm.read_user_tick_numbers(_for)
    size: uint256 = convert(ns[1] - ns[0], uint256)

    if debt == 0:
        # Allow to withdraw all assets even when underwater
        xy: uint256[2] = amm.withdraw(_for, _for)
        log UserState(_for, 0, 0, 0, 0)
        log Repay(_for, xy[1], d_debt)

    else:
        active_band: int256 = amm.active_band()
        if ns[0] > active_band:
            # Not in liquidation - can move bands
            xy: uint256[2] = amm.withdraw(_for, ZERO_ADDRESS)
            n1: int256 = self._calculate_debt_n1(xy[1], debt, size)
            assert n1 > active_band, "Not enough collateral"
            n2: int256 = n1 + ns[1] - ns[0]
            amm.deposit_range(_for, xy[1], n1, n2, False)
            log UserState(_for, xy[1], debt, n1, n2)
            log Repay(_for, 0, d_debt)
        else:
            # Underwater - cannot move band but can avoid a bad liquidation
            log UserState(_for, MAX_UINT256, debt, ns[0], ns[1])
            log Repay(_for, 0, d_debt)

    # If we withdrew already - will burn less!
    STABLECOIN.burnFrom(msg.sender, d_debt)

    self.loans[_for] = Loan({initial_debt: debt, rate_mul: rate_mul})
    total_debt: uint256 = self._total_debt.initial_debt * rate_mul / self._total_debt.rate_mul
    self._total_debt.initial_debt = max(total_debt, d_debt) - d_debt
    self._total_debt.rate_mul = rate_mul


@internal
@view
def _health(amm: AMM, user: address, debt: uint256, full: bool) -> int256:
    """
    Returns position health normalized to 1e18 for the user.
    Liquidation starts when < 0, however devaluation of collateral doesn't cause liquidation
    """
    _debt: int256 = convert(debt, int256)
    assert debt > 0, "Loan doesn't exist"
    xmax: int256 = convert(amm.get_x_down(user), int256)
    ld: int256 = convert(self.liquidation_discount, int256)
    non_discounted: int256 = xmax * 10**18 / _debt - 10**18

    if full:
        active_band: int256 = amm.active_band()
        ns: int256[2] = amm.read_user_tick_numbers(user) # ns[1] > ns[0]
        if ns[0] > active_band:  # We are not in liquidation mode
            p: int256 = convert(amm.price_oracle(), int256)
            p_up: int256 = convert(amm.p_oracle_up(ns[0]), int256)
            if p > p_up:
                collateral: int256 = convert(amm.get_y_up(user), int256)
                non_discounted += (p - p_up) * collateral / _debt

    return non_discounted - xmax * ld / _debt


@internal
def _liquidate(user: address, min_x: uint256, health_limit: uint256):
    debt: uint256 = 0
    rate_mul: uint256 = 0
    debt, rate_mul = self._debt(user)
    amm: AMM = self.amm

    if health_limit != 0:
        assert self._health(amm, user, debt, True) < convert(health_limit, int256), "Not enough rekt"

    # Send all the sender's stablecoin and collateral to our contract
    xy: uint256[2] = amm.withdraw(user, ZERO_ADDRESS)  # [stable, collateral]

    # x increase in same block -> price up -> good
    # x decrease in same block -> price down -> bad
    assert xy[0] >= min_x, "Sandwich"

    min_amm_burn: uint256 = min(xy[0], debt)
    if min_amm_burn != 0:
        STABLECOIN.burnFrom(amm.address, min_amm_burn)

    if debt > xy[0]:
        # Request what's left from user
        STABLECOIN.burnFrom(msg.sender, debt - xy[0])
    else:
        # Return what's left to user
        amm.rugpull(STABLECOIN.address, msg.sender, xy[0] - debt)

    amm.rugpull(self.collateral_token.address, msg.sender, xy[1])

    self.loans[user] = Loan({initial_debt: 0, rate_mul: rate_mul})
    log UserState(user, 0, 0, 0, 0)
    log Repay(user, xy[1], debt)
    log Liquidate(msg.sender, user, xy[1], xy[0], debt)

    d: uint256 = self._total_debt.initial_debt * rate_mul / self._total_debt.rate_mul
    self._total_debt.initial_debt = max(d, debt) - debt
    self._total_debt.rate_mul = rate_mul


@external
@nonreentrant('lock')
def liquidate(user: address, min_x: uint256):
    self._liquidate(user, min_x, self.liquidation_discount)


@external
@nonreentrant('lock')
def self_liquidate(min_x: uint256):
    self._liquidate(msg.sender, min_x, 0)


@view
@external
def tokens_to_liquidate(user: address) -> uint256:
    xy: uint256[2] = self.amm.get_sum_xy(user)
    return max(self._debt_ro(user), xy[0]) - xy[0]


@view
@external
def health(user: address, full: bool = False) -> int256:
    """
    Returns position health normalized to 1e18 for the user.
    Liquidation starts when < 0, however devaluation of collateral doesn't cause liquidation
    """
    return self._health(self.amm, user, self._debt_ro(user), full)


@view
@external
def amm_price() -> uint256:
    return self.amm.get_p()


@view
@external
def user_prices(user: address) -> uint256[2]:  # Upper, lower
    amm: AMM = self.amm
    ns: int256[2] = amm.read_user_tick_numbers(user) # ns[1] > ns[0]
    return [amm.p_oracle_up(ns[0]), amm.p_oracle_down(ns[1])]


@view
@external
def user_state(user: address) -> uint256[3]:  # collateral, stablecoin, debt
    xy: uint256[2] = self.amm.get_sum_xy(user)
    return [xy[1], xy[0], self._debt_ro(user)]


@external
def set_amm_fee(fee: uint256):
    assert msg.sender == FACTORY.admin()
    self.amm.set_fee(fee)


@external
def set_amm_admin_fee(fee: uint256):
    assert msg.sender == FACTORY.admin()
    self.amm.set_admin_fee(fee)


@external
def set_monetary_policy(monetary_policy: address):
    assert msg.sender == FACTORY.admin()
    self.monetary_policy = MonetaryPolicy(monetary_policy)
    MonetaryPolicy(monetary_policy).rate_write()
    log SetMonetaryPolicy(monetary_policy)


@external
def set_debt_ceiling(_debt_ceiling: uint256):
    assert msg.sender == FACTORY.admin()
    self.debt_ceiling = _debt_ceiling
    log SetDebtCeiling(_debt_ceiling)


@external
def set_borrowing_discounts(loan_discount: uint256, liquidation_discount: uint256):
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
    supply: uint256 = STABLECOIN.totalSupply()
    rate_mul: uint256 = self.amm.get_rate_mul()
    loan: Loan = self._total_debt
    loan.initial_debt = loan.initial_debt * rate_mul / loan.rate_mul
    if loan.initial_debt > supply:
        return loan.initial_debt - supply
    else:
        return 0


@external
@nonreentrant('lock')
def collect_fees() -> uint256:
    supply: uint256 = STABLECOIN.totalSupply()
    rate_mul: uint256 = self._rate_mul_w(self.amm)
    loan: Loan = self._total_debt
    loan.initial_debt = loan.initial_debt * rate_mul / loan.rate_mul
    if loan.initial_debt > supply:
        _to: address = FACTORY.fee_receiver()
        supply = loan.initial_debt - supply
        STABLECOIN.mint(_to, supply)
        log CollectFees(supply, loan.initial_debt)
        return supply
    else:
        log CollectFees(0, loan.initial_debt)
        return 0
