# @version 0.4.3
"""
@title AggMonetaryPolicy - monetary policy based on aggregated prices for crvUSD
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2025 - all rights reserved
"""
# TODO comment on suboptimal rate


from curve_stablecoin.interfaces import IPriceOracle
from curve_stablecoin.interfaces import IControllerFactory
from curve_stablecoin.interfaces import IPegKeeper
from curve_stablecoin.interfaces import IAggMonetaryPolicy4
from snekmate.utils import math
from snekmate.auth import ownable

implements: IAggMonetaryPolicy4
initializes: ownable

exports: (
    ownable.transfer_ownership,
)


rate0: public(uint256)
sigma: public(int256)  # 2 * 10**16 for example
target_debt_fraction: public(uint256)
extra_const: public(uint256)

_peg_keepers: IPegKeeper[1001]
# https://github.com/vyperlang/vyper/issues/4721
@external
@view
def peg_keepers(i: uint256) -> IPegKeeper:
    """
    @notice Get peg keeper at index
    """
    return self._peg_keepers[i]

PRICE_ORACLE: public(immutable(IPriceOracle))
CONTROLLER_FACTORY: public(immutable(IControllerFactory))

# Cache for controllers
MAX_CONTROLLERS: constant(uint256) = 50000
n_controllers: public(uint256)
controllers: public(address[MAX_CONTROLLERS])


DEBT_CANDLE_TIME: constant(uint256) = 86400 // 2
min_debt_candles: public(HashMap[address, IAggMonetaryPolicy4.DebtCandle])


MAX_TARGET_DEBT_FRACTION: constant(uint256) = 10**18
MAX_SIGMA: constant(int256) = 10**18
MIN_SIGMA: constant(int256) = 10**14
MAX_EXP: constant(uint256) = 1000 * 10**18
MAX_RATE: constant(uint256) = 43959106799  # 300% APY
TARGET_REMAINDER: constant(uint256) = 10**17  # rate is x1.9 when 10% left before ceiling
MAX_EXTRA_CONST: constant(uint256) = MAX_RATE


debt_ratio_ema_time: public(uint256)

prev_ema_debt_ratio_timestamp: public(uint256)
prev_ema_debt_ratio: public(uint256)


@deploy
def __init__(admin: address,
             price_oracle: IPriceOracle,
             controller_factory: IControllerFactory,
             peg_keepers: IPegKeeper[5],
             rate: uint256,
             sigma: int256,
             target_debt_fraction: uint256,
             extra_const: uint256,
             debt_ratio_ema_time: uint256):
    ownable.__init__()
    ownable._transfer_ownership(admin)
    PRICE_ORACLE = price_oracle
    CONTROLLER_FACTORY = controller_factory
    for i: uint256 in range(5):
        if peg_keepers[i].address == empty(address):
            break
        self._peg_keepers[i] = peg_keepers[i]

    assert sigma >= MIN_SIGMA
    assert sigma <= MAX_SIGMA
    assert target_debt_fraction > 0
    assert target_debt_fraction <= MAX_TARGET_DEBT_FRACTION
    assert rate <= MAX_RATE
    assert extra_const <= MAX_EXTRA_CONST
    assert debt_ratio_ema_time > 0
    self.rate0 = rate
    self.sigma = sigma
    self.target_debt_fraction = target_debt_fraction
    self.extra_const = extra_const
    self.prev_ema_debt_ratio_timestamp = block.timestamp
    self.prev_ema_debt_ratio = target_debt_fraction
    self.debt_ratio_ema_time = debt_ratio_ema_time
    log IAggMonetaryPolicy4.SetRate(rate=rate)
    log IAggMonetaryPolicy4.SetSigma(sigma=sigma)
    log IAggMonetaryPolicy4.SetTargetDebtFraction(target_debt_fraction=target_debt_fraction)
    log IAggMonetaryPolicy4.SetExtraConst(extra_const=extra_const)
    log IAggMonetaryPolicy4.SetDebtRatioEmaTime(ema_time=debt_ratio_ema_time)


@external
@view
def admin() -> address:
    return ownable.owner


@external
def add_peg_keeper(pk: IPegKeeper):
    ownable._check_owner()
    assert pk.address != empty(address)
    for i: uint256 in range(1000):
        _pk: IPegKeeper = self._peg_keepers[i]
        assert _pk != pk, "Already added"
        if _pk.address == empty(address):
            self._peg_keepers[i] = pk
            log IAggMonetaryPolicy4.AddPegKeeper(peg_keeper=pk.address)
            break


@external
def remove_peg_keeper(pk: IPegKeeper):
    ownable._check_owner()
    replaced_peg_keeper: uint256 = 10000
    for i: uint256 in range(1001):  # 1001th element is always 0x0
        _pk: IPegKeeper = self._peg_keepers[i]
        if _pk == pk:
            replaced_peg_keeper = i
            log IAggMonetaryPolicy4.RemovePegKeeper(peg_keeper=pk.address)
        if _pk.address == empty(address):
            if replaced_peg_keeper < i:
                if replaced_peg_keeper < i - 1:
                    self._peg_keepers[replaced_peg_keeper] = self._peg_keepers[i - 1]
                self._peg_keepers[i - 1] = IPegKeeper(empty(address))
            break




@internal
@view
def get_total_debt(_for: address) -> (uint256, uint256):
    n_controllers: uint256 = self.n_controllers
    total_debt: uint256 = 0
    debt_for: uint256 = 0

    for i: uint256 in range(MAX_CONTROLLERS):
        if i >= n_controllers:
            break
        controller: address = self.controllers[i]
        if controller == empty(address):
            continue

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
    candle: IAggMonetaryPolicy4.DebtCandle = self.min_debt_candles[_for]

    if block.timestamp < candle.timestamp // DEBT_CANDLE_TIME * DEBT_CANDLE_TIME + DEBT_CANDLE_TIME:
        if candle.candle0 > 0:
            out = min(candle.candle0, candle.candle1)
        else:
            out = candle.candle1
    elif block.timestamp < candle.timestamp // DEBT_CANDLE_TIME * DEBT_CANDLE_TIME + DEBT_CANDLE_TIME * 2:
        out = candle.candle1

    return out


@internal
def save_candle(_for: address, _value: uint256):
    candle: IAggMonetaryPolicy4.DebtCandle = self.min_debt_candles[_for]

    if candle.timestamp == 0 and _value == 0:
        # This record did not exist before, and value is zero -> not recording anything
        return

    if block.timestamp >= candle.timestamp // DEBT_CANDLE_TIME * DEBT_CANDLE_TIME + DEBT_CANDLE_TIME:
        if block.timestamp < candle.timestamp // DEBT_CANDLE_TIME * DEBT_CANDLE_TIME + DEBT_CANDLE_TIME * 2:
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
def calculate_ema_debt_ratio(total_debt: uint256) -> uint256:
    pk_debt: uint256 = 0
    for pk: IPegKeeper in self._peg_keepers:
        if pk.address == empty(address):
            break
        pk_debt += staticcall pk.debt()

    if total_debt == 0:
        return self.target_debt_fraction

    ratio: uint256 = 10**18 * pk_debt // total_debt
    mul: uint256 = 10**18
    dt: uint256 = block.timestamp - self.prev_ema_debt_ratio_timestamp
    if dt > 0:
        mul = convert(math._wad_exp(-convert(dt * 10**18 // self.debt_ratio_ema_time, int256)), uint256)

    return (self.prev_ema_debt_ratio * mul + ratio * (10**18 - mul)) // 10**18
    


@internal
@view
def calculate_rate(_for: address, _price: uint256, ro: bool) -> (uint256, uint256):
    sigma: int256 = self.sigma
    target_debt_fraction: uint256 = self.target_debt_fraction

    p: int256 = convert(_price, int256)

    total_debt: uint256 = 0
    debt_for: uint256 = 0
    total_debt, debt_for = self.read_debt(_for, ro)
    ema_debt_ratio: uint256 = self.calculate_ema_debt_ratio(total_debt)

    power: int256 = (10**18 - p) * 10**18 // sigma  # high price -> negative pow -> low rate
    power -= convert(ema_debt_ratio * 10**18 // target_debt_fraction, int256)

    # Rate accounting for crvUSD price and PegKeeper debt
    rate: uint256 = self.rate0 * min(convert(math._wad_exp(power), uint256), MAX_EXP) // 10**18 + self.extra_const

    # Account for individual debt ceiling to dynamically tune rate depending on filling the market
    ceiling: uint256 = staticcall CONTROLLER_FACTORY.debt_ceiling(_for)
    if ceiling > 0:
        f: uint256 = min(debt_for * 10**18 // ceiling, 10**18 - TARGET_REMAINDER // 1000)
        rate = min(rate * ((10**18 - TARGET_REMAINDER) + TARGET_REMAINDER * 10**18 // (10**18 - f)) // 10**18, MAX_RATE)

    # Rate multiplication at different ceilings (target = 0.1):
    # debt = 0:
    #   new_rate = rate * ((1.0 - target) + target) = rate
    #
    # debt = ceiling:
    #   f = 1.0 - 0.1 / 1000 = 0.9999  # instead of infinity to avoid /0
    #   new_rate = min(rate * ((1.0 - target) + target / (1.0 - 0.9999)), max_rate) = max_rate
    #
    # debt = 0.9 * ceiling, target = 0.1
    #   f = 0.9
    #   new_rate = rate * ((1.0 - 0.1) + 0.1 / (1.0 - 0.9)) = rate * (1.0 + 1.0 - 0.1) = 1.9 * rate

    return rate, ema_debt_ratio


@view
@external
def rate(_for: address = msg.sender) -> uint256:
    return self.calculate_rate(_for, staticcall PRICE_ORACLE.price(), True)[0]


@external
def rate_write(_for: address = msg.sender) -> uint256:
    # Update controller list
    n_controllers: uint256 = self.n_controllers
    n_factory_controllers: uint256 = staticcall CONTROLLER_FACTORY.n_collaterals()
    if n_factory_controllers > n_controllers:
        self.n_controllers = n_factory_controllers
        for i: uint256 in range(MAX_CONTROLLERS):
            self.controllers[n_controllers] = staticcall CONTROLLER_FACTORY.controllers(n_controllers)
            n_controllers += 1
            if n_controllers >= n_factory_controllers:
                break

    # Update candles
    total_debt: uint256 = 0
    debt_for: uint256 = 0
    total_debt, debt_for = self.get_total_debt(_for)
    self.save_candle(empty(address), total_debt)
    self.save_candle(_for, debt_for)

    rate: uint256 = 0
    ema_debt_ratio: uint256 = 0
    rate, ema_debt_ratio = self.calculate_rate(_for, extcall PRICE_ORACLE.price_w(), False)
    self.prev_ema_debt_ratio = ema_debt_ratio
    self.prev_ema_debt_ratio_timestamp = block.timestamp

    return rate


@external
def set_rate(rate: uint256):
    ownable._check_owner()
    assert rate <= MAX_RATE
    self.rate0 = rate
    log IAggMonetaryPolicy4.SetRate(rate=rate)


@external
def set_sigma(sigma: int256):
    ownable._check_owner()
    assert sigma >= MIN_SIGMA
    assert sigma <= MAX_SIGMA

    self.sigma = sigma
    log IAggMonetaryPolicy4.SetSigma(sigma=sigma)


@external
def set_target_debt_fraction(target_debt_fraction: uint256):
    ownable._check_owner()
    assert target_debt_fraction <= MAX_TARGET_DEBT_FRACTION
    assert target_debt_fraction > 0

    self.target_debt_fraction = target_debt_fraction
    log IAggMonetaryPolicy4.SetTargetDebtFraction(target_debt_fraction=target_debt_fraction)


@external
def set_extra_const(extra_const: uint256):
    ownable._check_owner()
    assert extra_const <= MAX_EXTRA_CONST

    self.extra_const = extra_const
    log IAggMonetaryPolicy4.SetExtraConst(extra_const=extra_const)


@external
def set_debt_ratio_ema_time(ema_time: uint256):
    ownable._check_owner()
    assert ema_time > 0
    self.debt_ratio_ema_time = ema_time
    log IAggMonetaryPolicy4.SetDebtRatioEmaTime(ema_time=ema_time)
