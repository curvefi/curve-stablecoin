# @version 0.3.10
"""
@title AggMonetaryPolicy - monetary policy based on aggregated prices for crvUSD
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2023 - all rights reserved
"""

interface PegKeeper:
    def debt() -> uint256: view

interface PriceOracle:
    def price() -> uint256: view

interface ControllerFactory:
    def total_debt() -> uint256: view


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

MAX_TARGET_DEBT_FRACTION: constant(uint256) = 10**18
MAX_SIGMA: constant(uint256) = 10**18
MIN_SIGMA: constant(uint256) = 10**14
MAX_EXP: constant(uint256) = 1000 * 10**18
MAX_RATE: constant(uint256) = 43959106799  # 300% APY


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
    if power <= -41446531673892821376:
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
def calculate_rate() -> uint256:
    sigma: int256 = self.sigma
    target_debt_fraction: uint256 = self.target_debt_fraction

    p: int256 = convert(PRICE_ORACLE.price(), int256)
    pk_debt: uint256 = 0
    for pk in self.peg_keepers:
        if pk.address == empty(address):
            break
        pk_debt += pk.debt()

    power: int256 = (10**18 - p) * 10**18 / sigma  # high price -> negative pow -> low rate
    if pk_debt > 0:
        total_debt: uint256 = CONTROLLER_FACTORY.total_debt()
        if total_debt == 0:
            return 0
        else:
            power -= convert(pk_debt * 10**18 / total_debt * 10**18 / target_debt_fraction, int256)

    return self.rate0 * min(self.exp(power), MAX_EXP) / 10**18


@view
@external
def rate() -> uint256:
    return self.calculate_rate()


@external
def rate_write() -> uint256:
    # Not needed here but useful for more automated policies
    # which change rate0 - for example rate0 targeting some fraction pl_debt/total_debt
    return self.calculate_rate()


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
