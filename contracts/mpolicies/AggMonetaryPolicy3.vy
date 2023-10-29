# @version 0.3.9
"""
@title AggMonetaryPolicy - monetary policy based on aggregated prices for crvUSD
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2023 - all rights reserved
"""

# This version uses min(last day) debt when calculating per-market rates


interface PegKeeper:
    def debt() -> uint256: view

interface PriceOracle:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable

interface ControllerFactory:
    def total_debt() -> uint256: view
    def debt_ceiling(_for: address) -> uint256: view
    def n_collaterals() -> uint256: view
    def controllers(i: uint256) -> address: view

interface Controller:
    def total_debt() -> uint256: view


struct TotalDebts:
    total_debt: uint256
    controller_debt: uint256
    ceiling: uint256


event SetAdmin:
    admin: address

event AddPegKeeper:
    peg_keeper: indexed(address)

event RemovePegKeeper:
    peg_keeper: indexed(address)

event SetRate:
    rate: uint256

event SetSigma:
    sigma: uint256

event SetTargetDebtFraction:
    target_debt_fraction: uint256


admin: public(address)

rate0: public(uint256)
sigma: public(int256)  # 2 * 10**16 for example
target_debt_fraction: public(uint256)

peg_keepers: public(PegKeeper[1001])
PRICE_ORACLE: public(immutable(PriceOracle))
CONTROLLER_FACTORY: public(immutable(ControllerFactory))

# Cache for controllers
MAX_CONTROLLERS: constant(uint256) = 50000
n_controllers: public(uint256)
controllers: public(address[MAX_CONTROLLERS])


struct DebtCandle:
    candle0: uint256  # earlier 1/2 day candle
    candle1: uint256   # later 1/2 day candle
    timestamp: uint256

DEBT_CANDLE_TIME: constant(uint256) = 86400 / 2
min_debt_candles: public(HashMap[address, DebtCandle])


MAX_TARGET_DEBT_FRACTION: constant(uint256) = 10**18
MAX_SIGMA: constant(uint256) = 10**18
MIN_SIGMA: constant(uint256) = 10**14
MAX_EXP: constant(uint256) = 1000 * 10**18
MAX_RATE: constant(uint256) = 43959106799  # 300% APY
TARGET_REMAINDER: constant(uint256) = 10**17  # rate is x2 when 10% left before ceiling


@external
def __init__(admin: address,
             price_oracle: PriceOracle,
             controller_factory: ControllerFactory,
             peg_keepers: PegKeeper[5],
             rate: uint256,
             sigma: uint256,
             target_debt_fraction: uint256):
    self.admin = admin
    PRICE_ORACLE = price_oracle
    CONTROLLER_FACTORY = controller_factory
    for i in range(5):
        if peg_keepers[i].address == empty(address):
            break
        self.peg_keepers[i] = peg_keepers[i]

    assert sigma >= MIN_SIGMA
    assert sigma <= MAX_SIGMA
    assert target_debt_fraction <= MAX_TARGET_DEBT_FRACTION
    assert rate <= MAX_RATE
    self.rate0 = rate
    self.sigma = convert(sigma, int256)
    self.target_debt_fraction = target_debt_fraction


@external
def set_admin(admin: address):
    assert msg.sender == self.admin
    self.admin = admin
    log SetAdmin(admin)


@external
def add_peg_keeper(pk: PegKeeper):
    assert msg.sender == self.admin
    assert pk.address != empty(address)
    for i in range(1000):
        _pk: PegKeeper = self.peg_keepers[i]
        assert _pk != pk, "Already added"
        if _pk.address == empty(address):
            self.peg_keepers[i] = pk
            log AddPegKeeper(pk.address)
            break


@external
def remove_peg_keeper(pk: PegKeeper):
    assert msg.sender == self.admin
    replaced_peg_keeper: uint256 = 10000
    for i in range(1001):  # 1001th element is always 0x0
        _pk: PegKeeper = self.peg_keepers[i]
        if _pk == pk:
            replaced_peg_keeper = i
            log RemovePegKeeper(pk.address)
        if _pk.address == empty(address):
            if replaced_peg_keeper < i:
                if replaced_peg_keeper < i - 1:
                    self.peg_keepers[replaced_peg_keeper] = self.peg_keepers[i - 1]
                self.peg_keepers[i - 1] = PegKeeper(empty(address))
            break


@internal
@pure
def exp(power: int256) -> uint256:
    if power <= -42139678854452767551:
        return 0

    if power >= 135305999368893231589:
        # Return MAX_EXP when we are in overflow mode
        return MAX_EXP

    x: int256 = unsafe_div(unsafe_mul(power, 2**96), 10**18)

    k: int256 = unsafe_div(
        unsafe_add(
            unsafe_div(unsafe_mul(x, 2**96), 54916777467707473351141471128),
            2**95),
        2**96)
    x = unsafe_sub(x, unsafe_mul(k, 54916777467707473351141471128))

    y: int256 = unsafe_add(x, 1346386616545796478920950773328)
    y = unsafe_add(unsafe_div(unsafe_mul(y, x), 2**96), 57155421227552351082224309758442)
    p: int256 = unsafe_sub(unsafe_add(y, x), 94201549194550492254356042504812)
    p = unsafe_add(unsafe_div(unsafe_mul(p, y), 2**96), 28719021644029726153956944680412240)
    p = unsafe_add(unsafe_mul(p, x), (4385272521454847904659076985693276 * 2**96))

    q: int256 = x - 2855989394907223263936484059900
    q = unsafe_add(unsafe_div(unsafe_mul(q, x), 2**96), 50020603652535783019961831881945)
    q = unsafe_sub(unsafe_div(unsafe_mul(q, x), 2**96), 533845033583426703283633433725380)
    q = unsafe_add(unsafe_div(unsafe_mul(q, x), 2**96), 3604857256930695427073651918091429)
    q = unsafe_sub(unsafe_div(unsafe_mul(q, x), 2**96), 14423608567350463180887372962807573)
    q = unsafe_add(unsafe_div(unsafe_mul(q, x), 2**96), 26449188498355588339934803723976023)

    return shift(
        unsafe_mul(convert(unsafe_div(p, q), uint256), 3822833074963236453042738258902158003155416615667),
        unsafe_sub(k, 195))


@internal
@view
def get_total_debt(_for: address) -> (uint256, uint256):
    n_controllers: uint256 = self.n_controllers
    total_debt: uint256 = 0
    debt_for: uint256 = 0

    for i in range(MAX_CONTROLLERS):
        if i >= n_controllers:
            break
        controller: address = self.controllers[i]

        success: bool = False
        res: Bytes[32] = empty(Bytes[32])
        success, res = raw_call(controller, method_id("total_debt()"), max_outsize=32, is_static_call=True, revert_on_failure=False)
        debt: uint256 = convert(res, uint256)
        total_debt += debt
        if controller == _for:
            debt_for = debt

    return total_debt, debt_for


@internal
@view
def read_candle(_for: address) -> uint256:
    out: uint256 = 0
    candle: DebtCandle = self.min_debt_candles[_for]

    if block.timestamp < candle.timestamp / DEBT_CANDLE_TIME * DEBT_CANDLE_TIME + DEBT_CANDLE_TIME:
        if candle.candle0 > 0:
            out = min(candle.candle0, candle.candle1)
        else:
            out = candle.candle1
    elif block.timestamp < candle.timestamp / DEBT_CANDLE_TIME * DEBT_CANDLE_TIME + DEBT_CANDLE_TIME * 2:
        out = candle.candle1

    return out


@internal
def save_candle(_for: address, _value: uint256):
    candle: DebtCandle = self.min_debt_candles[_for]

    if block.timestamp >= candle.timestamp / DEBT_CANDLE_TIME * DEBT_CANDLE_TIME + DEBT_CANDLE_TIME:
        if block.timestamp < candle.timestamp / DEBT_CANDLE_TIME * DEBT_CANDLE_TIME + DEBT_CANDLE_TIME * 2:
            candle.candle0 = candle.candle1
            candle.candle1 = _value
        else:
            candle.candle0 = _value
            candle.candle1 = _value
    else:
        candle.candle1 = min(candle.candle1, _value)

    candle.timestamp = block.timestamp
    self.min_debt_candles[_for] = candle


@internal
@view
def read_debt(_for: address, ro: bool) -> (uint256, uint256):
    debt_total: uint256 = self.read_candle(empty(address))
    debt_for: uint256 = self.read_candle(_for)
    fresh_total: uint256 = 0
    fresh_for: uint256 = 0

    if ro:
        fresh_total, fresh_for = self.get_total_debt(_for)
        if debt_total > 0:
            debt_total = min(debt_total, fresh_total)
        else:
            debt_total = fresh_total
        if debt_for > 0:
            debt_for = min(debt_for, fresh_for)
        else:
            debt_for = fresh_for

    else:
        if debt_total == 0 or debt_for == 0:
            fresh_total, fresh_for = self.get_total_debt(_for)
            if debt_total == 0:
                debt_total = fresh_total
            if debt_for == 0:
                debt_for = fresh_for

    return debt_total, debt_for


@internal
@view
def calculate_rate(_for: address, _price: uint256, ro: bool) -> uint256:
    sigma: int256 = self.sigma
    target_debt_fraction: uint256 = self.target_debt_fraction

    p: int256 = convert(_price, int256)
    pk_debt: uint256 = 0
    for pk in self.peg_keepers:
        if pk.address == empty(address):
            break
        pk_debt += pk.debt()

    total_debt: uint256 = 0
    debt_for: uint256 = 0
    total_debt, debt_for = self.read_debt(_for, ro)

    power: int256 = (10**18 - p) * 10**18 / sigma  # high price -> negative pow -> low rate
    if pk_debt > 0:
        if total_debt == 0:
            return 0
        else:
            power -= convert(pk_debt * 10**18 / total_debt * 10**18 / target_debt_fraction, int256)

    # Rate accounting for crvUSD price and PegKeeper debt
    rate: uint256 = self.rate0 * min(self.exp(power), MAX_EXP) / 10**18

    # Account for individual debt ceiling to dynamically tune rate depending on filling the market
    ceiling: uint256 = CONTROLLER_FACTORY.debt_ceiling(_for)
    if ceiling > 0:
        f: uint256 = min(debt_for * 10**18 / ceiling, 10**18 - TARGET_REMAINDER / 1000)
        rate = min(rate * ((10**18 - TARGET_REMAINDER) + TARGET_REMAINDER * 10**18 / (10**18 - f)) / 10**18, MAX_RATE)

    return rate


@view
@external
def rate(_for: address = msg.sender) -> uint256:
    return self.calculate_rate(_for, PRICE_ORACLE.price(), True)


@external
def rate_write(_for: address = msg.sender) -> uint256:
    # Update controller list
    n_controllers: uint256 = self.n_controllers
    n_factory_controllers: uint256 = CONTROLLER_FACTORY.n_collaterals()
    if n_factory_controllers > n_controllers:
        self.n_controllers = n_factory_controllers
        for i in range(MAX_CONTROLLERS):
            self.controllers[n_controllers] = CONTROLLER_FACTORY.controllers(n_controllers)
            n_controllers += 1
            if n_controllers >= n_factory_controllers:
                break

    # Update candles
    total_debt: uint256 = 0
    debt_for: uint256 = 0
    total_debt, debt_for = self.get_total_debt(_for)
    self.save_candle(empty(address), total_debt)
    self.save_candle(_for, debt_for)

    return self.calculate_rate(_for, PRICE_ORACLE.price_w(), False)


@external
def set_rate(rate: uint256):
    assert msg.sender == self.admin
    assert rate <= MAX_RATE
    self.rate0 = rate
    log SetRate(rate)


@external
def set_sigma(sigma: uint256):
    assert msg.sender == self.admin
    assert sigma >= MIN_SIGMA
    assert sigma <= MAX_SIGMA

    self.sigma = convert(sigma, int256)
    log SetSigma(sigma)


@external
def set_target_debt_fraction(target_debt_fraction: uint256):
    assert msg.sender == self.admin
    assert target_debt_fraction <= MAX_TARGET_DEBT_FRACTION

    self.target_debt_fraction = target_debt_fraction
    log SetTargetDebtFraction(target_debt_fraction)
