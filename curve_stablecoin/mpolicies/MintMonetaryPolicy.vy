# @version 0.4.3

"""
@title MintMonetaryPolicy - monetary policy based on aggregated prices for crvUSD
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2025 - all rights reserved
@custom:kill To kill this contract just kill the controller it is attached to.
"""
# TODO comment on suboptimal rate
# TODO add natspec
# TODO explain decision to stick to candles


from curve_stablecoin.interfaces import IPriceOracle
from curve_stablecoin.interfaces import IControllerFactory
from curve_stablecoin.interfaces import IPegKeeper
from curve_stablecoin.interfaces import IMintMonetaryPolicy
from curve_stablecoin import constants as c
from snekmate.utils import math
from snekmate.auth import ownable

implements: IMintMonetaryPolicy
initializes: ownable

exports: ownable.transfer_ownership

rate0: public(uint256)
sigma: public(int256)  # 2 * 10**16 for example
target_debt_fraction: public(uint256)
extra_const: public(uint256)

_peg_keepers: IPegKeeper[1001]
# https://github.com/vyperlang/vyper/issues/4721
@external
@view
def peg_keepers(_i: uint256) -> IPegKeeper:
    """
    @notice Get peg keeper at index
    """
    return self._peg_keepers[_i]


PRICE_ORACLE: public(immutable(IPriceOracle))
CONTROLLER_FACTORY: public(immutable(IControllerFactory))

# Cache for controllers
MAX_CONTROLLERS: constant(uint256) = 50000
n_controllers: public(uint256)
controllers: public(address[MAX_CONTROLLERS])

DEBT_CANDLE_TIME: constant(uint256) = 86400 // 2
min_debt_candles: public(HashMap[address, IMintMonetaryPolicy.DebtCandle])


# https://github.com/vyperlang/vyper/issues/4723
WAD: constant(uint256) = c.WAD
SWAD: constant(int256) = c.SWAD
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
def __init__(
    _admin: address,
    _price_oracle: IPriceOracle,
    _controller_factory: IControllerFactory,
    _peg_keepers: IPegKeeper[5],
    _rate: uint256,
    _sigma: int256,
    _target_debt_fraction: uint256,
    _extra_const: uint256,
    _debt_ratio_ema_time: uint256,
):
    ownable.__init__()
    ownable._transfer_ownership(_admin)
    PRICE_ORACLE = _price_oracle
    CONTROLLER_FACTORY = _controller_factory
    for i: uint256 in range(5):
        if _peg_keepers[i].address == empty(address):
            break
        self._peg_keepers[i] = _peg_keepers[i]

    self._set_sigma(_sigma)
    self._set_target_debt_fraction(_target_debt_fraction)
    self._set_rate(_rate)
    self._set_extra_const(_extra_const)
    self._set_debt_ratio_ema_time(_debt_ratio_ema_time)

    self.prev_ema_debt_ratio_timestamp = block.timestamp
    self.prev_ema_debt_ratio = _target_debt_fraction


@external
@view
def admin() -> address:
    return ownable.owner


@external
def add_peg_keeper(_pk: IPegKeeper):
    ownable._check_owner()
    assert _pk.address != empty(address)
    for i: uint256 in range(1000):
        pk: IPegKeeper = self._peg_keepers[i]
        assert pk != _pk, "Already added"
        if pk.address == empty(address):
            self._peg_keepers[i] = _pk
            log IMintMonetaryPolicy.AddPegKeeper(peg_keeper=_pk.address)
            break


@external
def remove_peg_keeper(_pk: IPegKeeper):
    ownable._check_owner()
    replaced_peg_keeper: uint256 = 10000
    for i: uint256 in range(1001):  # 1001th element is always 0x0
        pk: IPegKeeper = self._peg_keepers[i]
        if pk == _pk:
            replaced_peg_keeper = i
            log IMintMonetaryPolicy.RemovePegKeeper(peg_keeper=_pk.address)
        if pk.address == empty(address):
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
        success, res = raw_call(
            controller,
            method_id("total_debt()"),
            max_outsize=32,
            is_static_call=True,
            revert_on_failure=False,
        )
        debt: uint256 = convert(res, uint256)
        total_debt += debt
        if controller == _for:
            debt_for = debt
    return total_debt, debt_for


@internal
@view
def read_candle(_for: address) -> uint256:
    out: uint256 = 0
    candle: IMintMonetaryPolicy.DebtCandle = self.min_debt_candles[_for]

    if block.timestamp < candle.timestamp // DEBT_CANDLE_TIME * DEBT_CANDLE_TIME + DEBT_CANDLE_TIME:
        if candle.candle0 > 0:
            out = min(candle.candle0, candle.candle1)
        else:
            out = candle.candle1
    elif (
        block.timestamp
        < candle.timestamp // DEBT_CANDLE_TIME * DEBT_CANDLE_TIME + DEBT_CANDLE_TIME * 2
    ):
        out = candle.candle1

    return out


@internal
def save_candle(_for: address, _value: uint256):
    candle: IMintMonetaryPolicy.DebtCandle = self.min_debt_candles[_for]

    if candle.timestamp == 0 and _value == 0:
        # This record did not exist before, and value is zero -> not recording anything
        return

    if (
        block.timestamp
        >= candle.timestamp // DEBT_CANDLE_TIME * DEBT_CANDLE_TIME + DEBT_CANDLE_TIME
    ):
        if (
            block.timestamp
            < candle.timestamp // DEBT_CANDLE_TIME * DEBT_CANDLE_TIME + DEBT_CANDLE_TIME * 2
        ):
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
def read_debt(_for: address, _ro: bool) -> (uint256, uint256):
    debt_total: uint256 = self.read_candle(empty(address))
    debt_for: uint256 = self.read_candle(_for)
    fresh_total: uint256 = 0
    fresh_for: uint256 = 0

    if _ro:
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
def calculate_ema_debt_ratio(_total_debt: uint256) -> uint256:
    pk_debt: uint256 = 0
    for pk: IPegKeeper in self._peg_keepers:
        if pk.address == empty(address):
            break
        pk_debt += staticcall pk.debt()

    if _total_debt == 0:
        return self.target_debt_fraction

    ratio: uint256 = WAD * pk_debt // _total_debt
    mul: uint256 = WAD
    dt: uint256 = block.timestamp - self.prev_ema_debt_ratio_timestamp
    if dt > 0:
        mul = convert(
            math._wad_exp(-convert(dt * WAD // self.debt_ratio_ema_time, int256)), uint256
        )

    return (self.prev_ema_debt_ratio * mul + ratio * (WAD - mul)) // WAD


@internal
@view
def calculate_rate(_for: address, _price: uint256, _ro: bool) -> (uint256, uint256):
    """
    Ceiling tuning examples (target = 0.1):
      debt = 0: new_rate = rate * ((1.0 - target) + target)
      debt = ceiling: f = 0.9999 cap; new_rate = min(rate * ((1.0 - target) + target / (1.0 - 0.9999)), max_rate)
      debt = 0.9 * ceiling: f = 0.9; new_rate = rate * ((1.0 - 0.1) + 0.1 / (1.0 - 0.9)) = 1.9 * rate
    """
    sigma: int256 = self.sigma
    target_debt_fraction: uint256 = self.target_debt_fraction

    p: int256 = convert(_price, int256)

    total_debt: uint256 = 0
    debt_for: uint256 = 0
    total_debt, debt_for = self.read_debt(_for, _ro)
    ema_debt_ratio: uint256 = self.calculate_ema_debt_ratio(total_debt)

    power: int256 = (SWAD - p) * SWAD // sigma  # high price -> negative pow -> low rate
    power -= convert(ema_debt_ratio * WAD // target_debt_fraction, int256)

    # Rate accounting for crvUSD price and PegKeeper debt
    rate: uint256 = (
        self.rate0 * min(convert(math._wad_exp(power), uint256), MAX_EXP) // WAD + self.extra_const
    )

    # Account for individual debt ceiling to dynamically tune rate depending on filling the market
    ceiling: uint256 = staticcall CONTROLLER_FACTORY.debt_ceiling(_for)
    if ceiling > 0:
        f: uint256 = min(debt_for * WAD // ceiling, WAD - TARGET_REMAINDER // 1000)
        rate = min(
            rate * ((WAD - TARGET_REMAINDER) + TARGET_REMAINDER * WAD // (WAD - f)) // WAD, MAX_RATE
        )

    return rate, ema_debt_ratio


@external
@view
def rate(_for: address = msg.sender) -> uint256:
    return self.calculate_rate(_for, staticcall PRICE_ORACLE.price(), True)[0]


@external
def rate_write(_for: address = msg.sender) -> uint256:
    # Update controller list
    n_controllers: uint256 = self.n_controllers
    n_factory_controllers: uint256 = staticcall CONTROLLER_FACTORY.n_collaterals()
    if n_factory_controllers > n_controllers:
        self.n_controllers = n_factory_controllers
        for _: uint256 in range(MAX_CONTROLLERS):
            self.controllers[n_controllers] = staticcall CONTROLLER_FACTORY.controllers(
                n_controllers
            )
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


@internal
def _set_rate(_rate: uint256):
    assert _rate <= MAX_RATE
    self.rate0 = _rate
    log IMintMonetaryPolicy.SetRate(rate=_rate)


@external
def set_rate(_rate: uint256):
    ownable._check_owner()
    self._set_rate(_rate)


@internal
def _set_sigma(_sigma: int256):
    assert _sigma >= MIN_SIGMA
    assert _sigma <= MAX_SIGMA
    self.sigma = _sigma
    log IMintMonetaryPolicy.SetSigma(sigma=_sigma)


@external
def set_sigma(_sigma: int256):
    ownable._check_owner()
    self._set_sigma(_sigma)


@internal
def _set_target_debt_fraction(_target_debt_fraction: uint256):
    assert _target_debt_fraction > 0
    assert _target_debt_fraction <= MAX_TARGET_DEBT_FRACTION
    self.target_debt_fraction = _target_debt_fraction
    log IMintMonetaryPolicy.SetTargetDebtFraction(target_debt_fraction=_target_debt_fraction)


@external
def set_target_debt_fraction(_target_debt_fraction: uint256):
    ownable._check_owner()
    self._set_target_debt_fraction(_target_debt_fraction)


@internal
def _set_extra_const(_extra_const: uint256):
    assert _extra_const <= MAX_EXTRA_CONST
    self.extra_const = _extra_const
    log IMintMonetaryPolicy.SetExtraConst(extra_const=_extra_const)


@external
def set_extra_const(_extra_const: uint256):
    ownable._check_owner()
    self._set_extra_const(_extra_const)


@internal
def _set_debt_ratio_ema_time(_ema_time: uint256):
    assert _ema_time > 0
    self.debt_ratio_ema_time = _ema_time
    log IMintMonetaryPolicy.SetDebtRatioEmaTime(ema_time=_ema_time)


@external
def set_debt_ratio_ema_time(_ema_time: uint256):
    ownable._check_owner()
    self._set_debt_ratio_ema_time(_ema_time)
