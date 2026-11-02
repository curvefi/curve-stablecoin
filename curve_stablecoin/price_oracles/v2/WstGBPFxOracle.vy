# pragma version 0.4.3
# SPDX-License-Identifier: MIT
"""
@title wstGBP FX Oracle
@license MIT
@notice USD per wstGBP: capped redemption NAV times smoothed GBP/USD. crvUSD is $1.
@dev Adapted from Arb Capital's WsgemFxLlamalendOracle (Copyright (c) 2026 Arb Capital):
     https://github.com/Arb-Capital/wsgem-llamalend/blob/8596dfa09fb94a832017c65dab536a2e480dbc03/src/WsgemFxLlamalendOracle.sol
     NAV downside is immediate; paused NAV or unusable FX holds the last report.
"""

from curve_stablecoin.interfaces import IPriceOracle

implements: IPriceOracle


interface Wrapper:
    def burncost() -> uint256: view
    def pip() -> address: view
    def gem() -> address: view
    def decimals() -> uint8: view


interface Decimals:
    def decimals() -> uint8: view


interface FXEMA:
    def chainlinkFeed() -> address: view
    def OBSERVATIONS() -> uint256: view
    def INTERVAL() -> uint256: view


flag Spot:
    PAUSED
    LIVE_ZERO
    FX_DOWN
    QUOTE


event QuoteAnchored:
    quote: uint256


event PriceUpdated:
    price: uint256


event FxDown:
    heldPrice: uint256


event FxRestored:
    price: uint256


WAD: constant(uint256) = 10**18
MAX_QUOTE: constant(uint256) = 10**36
MAX_ELAPSED: public(constant(uint256)) = 7 * 86400
MAX_UPSIDE_SPEED: public(constant(uint256)) = 28_935_185_185  # 0.25% per day
MAX_FX_AGE: public(constant(uint256)) = 30 * 3600
READ_GAS: constant(uint256) = 300_000
EMA_READ_GAS: constant(uint256) = 4_000_000

WSGEM: public(immutable(Wrapper))
GEM: public(immutable(address))
PIP: public(immutable(address))
FX_FEED: public(immutable(address))
FX_EMA: public(immutable(address))
cachedQuote: public(uint256)
cachedTimestamp: public(uint256)
cachedPrice: public(uint256)
liveZeroReported: public(bool)
fxDown: public(bool)


@deploy
def __init__(wrapper: Wrapper, feed: address, ema: FXEMA):
    assert (
        wrapper.address != empty(address)
        and feed != empty(address)
        and ema.address != empty(address)
    )
    WSGEM = wrapper
    GEM = staticcall wrapper.gem()
    PIP = staticcall wrapper.pip()
    FX_FEED = feed
    FX_EMA = ema.address
    assert GEM != empty(address) and PIP != empty(address)
    assert staticcall wrapper.decimals() == 18 and staticcall Decimals(GEM).decimals() == 18
    assert staticcall Decimals(feed).decimals() == 8
    assert staticcall ema.chainlinkFeed() == feed
    assert staticcall ema.OBSERVATIONS() == 20 and staticcall ema.INTERVAL() == 30
    state: Spot = empty(Spot)
    quote: uint256 = 0
    fx: uint256 = 0
    state, quote, fx = self._spot()
    assert state == Spot.QUOTE, "unusable initial price"
    self.cachedQuote = quote
    self.cachedPrice = self._compose(quote, fx)
    self.cachedTimestamp = block.timestamp


@internal
@view
def _word(target: address, selector: Bytes[4], gas_limit: uint256) -> (bool, uint256):
    ok: bool = False
    data: Bytes[32] = b""
    ok, data = raw_call(
        target,
        selector,
        max_outsize=32,
        gas=gas_limit,
        is_static_call=True,
        revert_on_failure=False,
    )
    if not ok or len(data) < 32:
        return False, 0
    return True, convert(data, uint256)


@internal
@view
def _spot() -> (Spot, uint256, uint256):
    ok: bool = False
    value: uint256 = 0
    ok, value = self._word(PIP, method_id("read()"), READ_GAS)
    if not ok or value == 0:
        return Spot.PAUSED, 0, 0
    ok, value = self._word(WSGEM.address, method_id("burncost()"), READ_GAS)
    if not ok:
        return Spot.PAUSED, 0, 0
    if value == 0:
        return Spot.LIVE_ZERO, 0, 0
    quote: uint256 = min(value, MAX_QUOTE)

    # Check the raw round too: the EMA does not enforce freshness.
    data: Bytes[160] = b""
    ok, data = raw_call(
        FX_FEED,
        method_id("latestRoundData()"),
        max_outsize=160,
        gas=READ_GAS,
        is_static_call=True,
        revert_on_failure=False,
    )
    if not ok or len(data) < 160:
        return Spot.FX_DOWN, quote, 0
    answer: int256 = convert(slice(data, 32, 32), int256)
    updated_at: uint256 = convert(slice(data, 96, 32), uint256)
    if answer <= 0 or answer > 10**26 or updated_at == 0 or updated_at > block.timestamp:
        return Spot.FX_DOWN, quote, 0
    if block.timestamp - updated_at > MAX_FX_AGE:
        return Spot.FX_DOWN, quote, 0
    ok, value = self._word(FX_EMA, method_id("price()"), EMA_READ_GAS)
    if not ok or value == 0 or value > MAX_QUOTE:
        return Spot.FX_DOWN, quote, 0
    return Spot.QUOTE, quote, value


@internal
@view
def _ceiling() -> uint256:
    elapsed: uint256 = min(block.timestamp - self.cachedTimestamp, MAX_ELAPSED)
    return self.cachedQuote * (WAD + MAX_UPSIDE_SPEED * elapsed) // WAD


@internal
@pure
def _compose(quote: uint256, fx: uint256) -> uint256:
    return max(quote * fx // WAD, 1)


@internal
@view
def _price(state: Spot, quote: uint256, fx: uint256) -> uint256:
    if state == Spot.LIVE_ZERO or self.liveZeroReported and state != Spot.QUOTE:
        return 1
    if state != Spot.QUOTE:
        return self.cachedPrice
    return self._compose(min(quote, self._ceiling()), fx)


@external
@view
def price() -> uint256:
    state: Spot = empty(Spot)
    quote: uint256 = 0
    fx: uint256 = 0
    state, quote, fx = self._spot()
    return self._price(state, quote, fx)


@external
def price_w() -> uint256:
    state: Spot = empty(Spot)
    quote: uint256 = 0
    fx: uint256 = 0
    state, quote, fx = self._spot()
    limited: uint256 = min(quote, self._ceiling())
    result: uint256 = self._price(state, quote, fx)
    if state == Spot.QUOTE:
        # Persist after pricing; a failed write cannot change this block's quote.
        success: bool = raw_call(
            FX_EMA, method_id("price_w()"), max_outsize=0, gas=EMA_READ_GAS, revert_on_failure=False
        )
    self.cachedTimestamp = block.timestamp
    if state == Spot.LIVE_ZERO:
        self.liveZeroReported = True
    elif state == Spot.FX_DOWN:
        if not self.fxDown:
            log FxDown(heldPrice=result)
        self.fxDown = True
    elif state == Spot.QUOTE:
        self.liveZeroReported = False
        if self.fxDown:
            log FxRestored(price=result)
        self.fxDown = False
        if limited != self.cachedQuote:
            self.cachedQuote = limited
            log QuoteAnchored(quote=limited)
        if result != self.cachedPrice:
            self.cachedPrice = result
            log PriceUpdated(price=result)
    return result


@external
@view
def frozen() -> bool:
    return self._spot()[0] in (Spot.PAUSED | Spot.FX_DOWN)


@external
@view
def fxFrozen() -> bool:
    return self._spot()[0] == Spot.FX_DOWN


@external
@view
def quoteCeiling() -> uint256:
    return self._ceiling()
