# @version 0.3.1

interface AMM:
    def A() -> uint256: view
    def base_price() -> uint256: view
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
    def get_rate_mul() -> uint256: view
    def rugpull(coin: address, _to: address, val: uint256): nonpayable
    def set_rate(rate: int256) -> uint256: nonpayable
    def set_fee(fee: uint256): nonpayable

interface ERC20:
    def totalSupply() -> uint256: view
    def mint(_to: address, _value: uint256) -> bool: nonpayable
    def burnFrom(_to: address, _value: uint256) -> bool: nonpayable
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable

interface MonetaryPolicy:
    def rate_write() -> int256: nonpayable

interface Factory:
    def stablecoin() -> address: view
    def admin() -> address: view


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


struct Loan:
    initial_debt: uint256
    rate_mul: uint256


FACTORY: immutable(address)
STABLECOIN: immutable(address)
MIN_LIQUIDATION_DISCOUNT: constant(uint256) = 10**16 # Start liquidating when threshold reached
MAX_TICKS: constant(int256) = 50
MIN_TICKS: constant(int256) = 5

MAX_RATE: constant(int256) = 43959106799  # 400% APY
MIN_RATE: constant(int256) = -7075835584  # -20% APY

loans: HashMap[address, Loan]
_total_debt: Loan

amm: public(address)
collateral_token: public(address)
monetary_policy: public(address)
ltv: public(uint256)  # Loan to value at 1e18 base
liquidation_discount: public(uint256)
loan_discount: public(uint256)
debt_ceiling: public(uint256)

logAratio: public(uint256)  # log(A / (A - 1))  XXX remove pub


@external
def __init__(factory: address):
    FACTORY = factory
    STABLECOIN = Factory(factory).stablecoin()


@internal
@pure
def log2(_x: uint256) -> uint256:
    # adapted from: https://medium.com/coinmonks/9aef8515136e
    # and vyper log implementation
    res: uint256 = 0
    x: uint256 = _x
    for i in range(8):
        t: uint256 = 2**(7 - i)
        p: uint256 = 2**t
        if x >= p * 10**18:
            x /= p
            res += t * 10**18
    d: uint256 = 10**18
    for i in range(34):  # 10 decimals: math.log(10**10, 2) == 33.2. Need more?
        if (x >= 2 * 10**18):
            res += d
            x /= 2
        x = x * x / 10**18
        d /= 2
    return res


@external
def initialize(
    collateral_token: address,
    monetary_policy: address,
    loan_discount: uint256,
    liquidation_discount: uint256,
    amm: address,
    debt_ceiling: uint256):
    assert self.collateral_token == ZERO_ADDRESS

    self.collateral_token = collateral_token
    self.monetary_policy = monetary_policy

    assert loan_discount > liquidation_discount
    assert liquidation_discount >= MIN_LIQUIDATION_DISCOUNT
    self.liquidation_discount = liquidation_discount
    self.loan_discount = loan_discount
    self.debt_ceiling = debt_ceiling

    self.amm = amm
    A: uint256 = AMM(amm).A()
    self.logAratio = self.log2(A * 10**18 / (A - 1))


@internal
def _debt(user: address) -> (uint256, uint256):
    rate: int256 = MonetaryPolicy(self.monetary_policy).rate_write()
    if rate > MAX_RATE:
        rate = MAX_RATE
    if rate < MIN_RATE:
        rate = MIN_RATE
    rate_mul: uint256 = AMM(self.amm).set_rate(rate)
    loan: Loan = self.loans[user]
    return (loan.initial_debt * rate_mul / loan.rate_mul, rate_mul)


@internal
@view
def _debt_ro(user: address) -> uint256:
    rate_mul: uint256 = AMM(self.amm).get_rate_mul()
    loan: Loan = self.loans[user]
    return loan.initial_debt * rate_mul / loan.rate_mul


@external
@view
def debt(user: address) -> uint256:
    return self._debt_ro(user)


@external
@view
def total_debt() -> uint256:
    rate_mul: uint256 = AMM(self.amm).get_rate_mul()
    loan: Loan = self._total_debt
    return loan.initial_debt * rate_mul / loan.rate_mul


# n1 = log((collateral * p_base * (1 - discount)) / debt) / log(A / (A - 1)) - N / 2
# round that down
# n2 = n1 + N
@internal
@view
def _calculate_debt_n1(collateral: uint256, debt: uint256, N: uint256) -> int256:
    amm: address = self.amm
    n0: int256 = AMM(amm).active_band()
    p0: uint256 = AMM(amm).p_current_down(n0)
    # TODO If someone pumped the AMM and deposited
    # - it will be sold if the price goes back down
    # But this needs to be tested?

    collateral_val: uint256 = (collateral * p0 / 10**18 * (10**18 - self.loan_discount))
    assert collateral_val >= debt, "Debt is too high"
    n1_precise: uint256 = self.log2(collateral_val / debt) * 10**18 / self.logAratio - 10**18 * N / 2
    assert n1_precise >= 10**18, "Debt is too high"

    return convert(n1_precise / 10**18, int256) + n0


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
    amm: address = self.amm

    n1: int256 = self._calculate_debt_n1(collateral, debt, n)
    n2: int256 = n1 + convert(n, int256)

    rate_mul: uint256 = AMM(amm).set_rate(MonetaryPolicy(self.monetary_policy).rate_write())
    self.loans[msg.sender] = Loan({initial_debt: debt, rate_mul: rate_mul})
    self._total_debt.initial_debt = self._total_debt.initial_debt * rate_mul / self._total_debt.rate_mul + debt
    assert self._total_debt.initial_debt <= self.debt_ceiling, "Debt ceiling"
    self._total_debt.rate_mul = rate_mul

    AMM(amm).deposit_range(msg.sender, collateral, n1, n2, False)
    ERC20(self.collateral_token).transferFrom(msg.sender, amm, collateral)
    ERC20(STABLECOIN).mint(msg.sender, debt)

    log UserState(msg.sender, collateral, debt, n1, n2)
    log Borrow(msg.sender, collateral, debt)


@internal
def _add_collateral_borrow(d_collateral: uint256, d_debt: uint256, _for: address):
    debt: uint256 = 0
    rate_mul: uint256 = 0
    debt, rate_mul = self._debt(_for)
    assert debt > 0, "Loan doesn't exist"
    debt += d_debt
    amm: address = self.amm
    ns: int256[2] = AMM(amm).read_user_tick_numbers(_for)
    size: uint256 = convert(ns[1] - ns[0], uint256)

    xy: uint256[2] = AMM(amm).withdraw(_for, ZERO_ADDRESS)
    assert xy[0] == 0, "Already in underwater mode"
    xy[1] += d_collateral
    n1: int256 = self._calculate_debt_n1(xy[1], debt, size)
    assert n1 >= ns[0], "Not enough collateral"
    n2: int256 = n1 + ns[1] - ns[0]

    AMM(amm).deposit_range(_for, xy[1], n1, n2, False)
    self.loans[_for] = Loan({initial_debt: debt, rate_mul: rate_mul})

    if d_debt > 0:
        self._total_debt.initial_debt = self._total_debt.initial_debt * rate_mul / self._total_debt.rate_mul + d_debt
        assert self._total_debt.initial_debt <= self.debt_ceiling, "Debt ceiling"
        self._total_debt.rate_mul = rate_mul

    log Borrow(_for, d_collateral, d_debt)
    log UserState(_for, xy[1], debt, n1, n2)


@external
@nonreentrant('lock')
def add_collateral(collateral: uint256, _for: address):
    self._add_collateral_borrow(collateral, 0, _for)
    ERC20(self.collateral_token).transferFrom(msg.sender, self.amm, collateral)


@external
@nonreentrant('lock')
def borrow_more(collateral: uint256, debt: uint256):
    self._add_collateral_borrow(collateral, debt, msg.sender)
    ERC20(self.collateral_token).transferFrom(msg.sender, self.amm, collateral)
    ERC20(STABLECOIN).mint(msg.sender, debt)


@external
@nonreentrant('lock')
def repay(_d_debt: uint256, _for: address):
    # Or repay all for MAX_UINT256
    # Withdraw if debt become 0
    debt: uint256 = 0
    rate_mul: uint256 = 0
    debt, rate_mul = self._debt(_for)
    assert debt > 0, "Loan doesn't exist"
    d_debt: uint256 = _d_debt
    if _d_debt > debt:
        d_debt = debt
    ERC20(STABLECOIN).burnFrom(msg.sender, d_debt)
    debt -= d_debt

    amm: address = self.amm
    ns: int256[2] = AMM(amm).read_user_tick_numbers(_for)
    size: uint256 = convert(ns[1] - ns[0], uint256)

    if debt == 0:
        xy: uint256[2] = AMM(amm).withdraw(_for, _for)
        assert xy[0] == 0, "Already in underwater mode"
        log UserState(_for, 0, 0, 0, 0)
        log Repay(_for, xy[1], 0)

    else:
        xy: uint256[2] = AMM(amm).withdraw(_for, ZERO_ADDRESS)
        assert xy[0] == 0, "Already in underwater mode"
        n1: int256 = self._calculate_debt_n1(xy[1], debt, size)
        assert n1 >= ns[0], "Not enough collateral"
        n2: int256 = n1 + ns[1] - ns[0]
        AMM(amm).deposit_range(_for, xy[1], n1, n2, False)
        log UserState(_for, xy[1], debt, n1, n2)
        log Repay(_for, 0, d_debt)

    self.loans[_for] = Loan({initial_debt: debt, rate_mul: rate_mul})
    d: uint256 = self._total_debt.initial_debt * rate_mul / self._total_debt.rate_mul
    if d <= d_debt:
        self._total_debt.initial_debt = 0
    else:
        self._total_debt.initial_debt = d - d_debt
    self._total_debt.rate_mul = rate_mul


@external
@nonreentrant('lock')
def liquidate(user: address, max_x: uint256):
    # Take all the fiat in the AMM, up to the debt size, and cancel the debt
    # Return all funds to the liquidator
    debt: uint256 = 0
    rate_mul: uint256 = 0
    debt, rate_mul = self._debt(user)
    assert debt > 0, "Loan doesn't exist"
    amm: address = self.amm
    xmax: uint256 = AMM(amm).get_x_down(user)
    assert xmax * (10**18 - self.liquidation_discount) / 10**18 < debt, "Not enough rekt"

    xy: uint256[2] = AMM(amm).withdraw(user, ZERO_ADDRESS)  # [stable, collateral]
    assert xy[0] >= max_x, "Sandwich"
    if xy[0] < debt:
        ERC20(STABLECOIN).burnFrom(amm, xy[0])
        xy[0] = 0
    else:
        ERC20(STABLECOIN).burnFrom(amm, debt)
        xy[0] -= debt

    self.loans[user] = Loan({initial_debt: 0, rate_mul: rate_mul})
    if xy[0] > 0:
        AMM(amm).rugpull(STABLECOIN, msg.sender, xy[0])
    if xy[1] > 0:
        AMM(amm).rugpull(self.collateral_token, msg.sender, xy[1])

    log UserState(user, 0, 0, 0, 0)
    log Repay(user, xy[1], debt)
    log Liquidate(msg.sender, user, xy[1], xy[0], debt)


@external
@nonreentrant('lock')
def self_liquidate(max_x: uint256):
    # Take all the fiat in the AMM, up to the debt size, and cancel the debt
    # Don't allow if underwater
    debt: uint256 = 0
    rate_mul: uint256 = 0
    debt, rate_mul = self._debt(msg.sender)
    assert debt > 0, "Loan doesn't exist"
    amm: address = self.amm
    xmax: uint256 = AMM(amm).get_x_down(msg.sender)
    assert xmax * (10**18 - self.liquidation_discount) / 10**18 >= debt, "Too rekt"

    # Send all the sender's stablecoin and collateral to our contract
    xy: uint256[2] = AMM(amm).withdraw(msg.sender, ZERO_ADDRESS)  # [stable, collateral]
    assert xy[0] >= max_x, "Sandwich"

    if xy[0] < debt:
        # Partial liquidation:
        # Burn the part to liquidate and decrease the debt
        # Keep the rest of the debt but redeposit
        ERC20(STABLECOIN).burnFrom(amm, xy[0])

        ns: int256[2] = AMM(amm).read_user_tick_numbers(msg.sender)
        size: uint256 = convert(ns[1] - ns[0], uint256)
        debt -= xy[0]
        n1: int256 = self._calculate_debt_n1(xy[1], debt, size)
        assert n1 > AMM(amm).active_band(), "Not enough collateral"
        n2: int256 = n1 + ns[1] - ns[0]

        AMM(amm).deposit_range(msg.sender, xy[1], n1, n2, False)
        self.loans[msg.sender] = Loan({initial_debt: debt, rate_mul: rate_mul})
        log UserState(msg.sender, xy[1], debt, n1, n2)
        log Repay(msg.sender, 0, xy[0])

    else:
        # Full liquidation
        # burn what has to be burned and returned the assets
        ERC20(STABLECOIN).burnFrom(amm, debt)
        if xy[0] > debt:
            AMM(amm).rugpull(STABLECOIN, msg.sender, xy[0] - debt)
        AMM(amm).rugpull(self.collateral_token, msg.sender, xy[1])
        self.loans[msg.sender] = Loan({initial_debt: 0, rate_mul: rate_mul})
        log UserState(msg.sender, 0, 0, 0, 0)
        log Repay(msg.sender, xy[1], debt)
        xy[0] = debt

    # Total debt reduced by xy[0]
    if xy[0] > 0:
        d: uint256 = self._total_debt.initial_debt * rate_mul / self._total_debt.rate_mul
        if d <= xy[0]:
            self._total_debt.initial_debt = 0
        else:
            self._total_debt.initial_debt = d - xy[0]
        self._total_debt.rate_mul = rate_mul


@view
@external
def health(user: address) -> int256:
    """
    Returns position health normalized to 1e18 for the user.
    Liquidation starts when < 0, however devaluation of collateral doesn't cause liquidation
    """
    debt: uint256 = self._debt_ro(user)
    assert debt > 0, "Loan doesn't exist"
    xmax: uint256 = AMM(self.amm).get_x_down(user)
    return convert(xmax * (10**18 - self.liquidation_discount) / 10**18, int256) - convert(debt, int256)


@view
@external
def amm_price() -> uint256:
    return AMM(self.amm).get_p()


@view
@external
def user_prices(user: address) -> uint256[2]:  # Upper, lower
    amm: address = self.amm
    ns: int256[2] = AMM(amm).read_user_tick_numbers(user) # ns[1] > ns[0]
    return [AMM(amm).p_oracle_up(ns[0]), AMM(amm).p_oracle_down(ns[1])]


@view
@external
def user_state(user: address) -> uint256[3]:  # collateral, stablecoin, debt
    xy: uint256[2] = AMM(self.amm).get_sum_xy(user)
    return [xy[1], xy[0], self._debt_ro(user)]


@external
def set_fee(fee: uint256):
    assert msg.sender == Factory(FACTORY).admin()
    AMM(self.amm).set_fee(fee)


@external
def set_monetary_policy(monetary_policy: address):
    assert msg.sender == Factory(FACTORY).admin()
    self.monetary_policy = monetary_policy
    MonetaryPolicy(monetary_policy).rate_write()


@external
def set_debt_ceiling(_debt_ceiling: uint256):
    assert msg.sender == Factory(FACTORY).admin()
    self.debt_ceiling = _debt_ceiling

# XXX feed back debt rate to AMM
# XXX stabilizer
