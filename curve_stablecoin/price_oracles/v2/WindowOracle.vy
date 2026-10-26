# pragma version 0.4.3
"""
@title WindowOracle
@author Curve.Finance
@license Copyright (c) Curve.Finance, 2020-2026 - all rights reserved
@notice Price oracle for crvUSD from a Curve pool whose price_oracle is an
        EMA of block-end prices: tricrypto-ng, twocrypto-ng, FXSwap,
        stableswap-ng and the crvUSD factory stableswap pools. Reads only
        that price_oracle (and its ma_time) and recovers from its increment
        the average block-end price since the last write; the reported price
        follows the highest and lowest of those over the last WINDOW seconds
        with time constant TAU, at most CAP per 12 s.
@dev Nothing a caller does inside a block can change what it reads, so
     `price_w` may be called by anyone. Once the last write is WINDOW
     seconds old, `price` follows the average since that write alone.
     The price is of coin `POOL_IX + 1` in coin 0, in USD, as the pool
     quotes it: stableswap-ng quotes a coin with a rate oracle (ERC4626,
     rebasing) per rate-scaled unit, and caps the price it averages at 2.
     With old tricrypto2 and the other pre-ng pools it is UNSAFE to use:
     their EMA moves inside a trade.
@custom:security security@curve.finance
@custom:kill There is no need to kill this contract, just kill the underlying market
"""

from curve_stablecoin.interfaces import IPriceOracle
from curve_stablecoin import constants as c
from snekmate.utils import math

implements: IPriceOracle


# Tricrypto-ng, twocrypto-ng, FXSwap, stableswap-ng, stableswap
interface Pool:
    def price_oracle(i: uint256 = 0) -> uint256: view  # Universal method!
    def coins(i: uint256) -> address: view
    def packed_rebalancing_params() -> uint256: view  # Crypto pools: ma_time in the low 64 bits
    def ma_exp_time() -> uint256: view  # Stableswap pools

interface StableAggregator:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable
    def stablecoin() -> address: view
    def last_price() -> uint256: view
    def last_timestamp() -> uint256: view

interface Stableswap:
    def price_oracle() -> uint256: view
    def coins(i: uint256) -> address: view


WAD: constant(uint256) = c.WAD
SWAD: constant(int256) = c.SWAD
# Observations kept, one per block: WINDOW / 12 + 1 are needed
N_OBS: constant(uint256) = 4

POOL: public(immutable(Pool))
POOL_IX: public(immutable(uint256))
# price_oracle() of a two-coin pool takes no index (except in stableswap-ng)
NO_ARGUMENT: public(immutable(bool))
STABLESWAP_AGGREGATOR: public(immutable(StableAggregator))
# crvUSD / coin 0 of the pool; empty when coin 0 is crvUSD
STABLESWAP: public(immutable(Stableswap))
STABLECOIN: public(immutable(address))
# crvUSD is coin 0 of STABLESWAP
IS_INVERSE: immutable(bool)
# ma_time sits in the low 64 bits of packed_rebalancing_params() (crypto pools) instead of ma_exp_time()
PACKED_MA_TIME: public(immutable(bool))

WINDOW: public(immutable(uint256))  # s
TAU: public(immutable(uint256))  # s
CAP: public(immutable(uint256))  # Max move of the band per 12 s, 1e18 = 100%
# USD conversion factor is re-read from the aggregator when older than this;
# the aggregator's last written price is taken when that is not older than this either
STALE: public(immutable(uint256))  # s

# hi (85 bits) | lo (85) | p (85)
packed_band: uint256
# timestamp (40) | next observation slot (24) | pool price_oracle at the last write (88) | factor (64) |
# factor timestamp (40)
packed_last: uint256
# Two observations per slot: timestamp (40) | average block-end price (88)
packed_obs: uint256[N_OBS // 2]


@deploy
def __init__(
        _pool: Pool,
        _ix: uint256,
        _stableswap: Stableswap,
        _stable_aggregator: StableAggregator,
        _window: uint256,
        _tau: uint256,
        _cap: uint256,
        _stale: uint256
    ):
    """
    @notice Configure the pool to price through and the band.
    @dev Whether the pool's `price_oracle` takes a coin-index argument, and
         where the pool keeps the ma_time of its EMA, are auto-detected and
         recorded in NO_ARGUMENT and PACKED_MA_TIME.
    @param _pool Curve pool whose `price_oracle` is an EMA of block-end prices.
    @param _ix Index passed to `price_oracle`: 1 = ETH in tricrypto; 0 in a pool of two coins.
    @param _stableswap crvUSD / coin 0 of the pool; empty when coin 0 is crvUSD.
    @param _stable_aggregator crvUSD stable aggregator, gives the crvUSD/USD price.
    @param _window Seconds of block-end prices the band takes the highest and lowest of.
    @param _tau Time constant (seconds) the band follows them with.
    @param _cap Max move of the band per 12 s (1e18 = 100%).
    @param _stale Age (seconds) after which the USD conversion factor, and the aggregator's last written price, is re-read.
    """
    POOL = _pool
    POOL_IX = _ix
    STABLESWAP_AGGREGATOR = _stable_aggregator
    STABLESWAP = _stableswap
    stablecoin: address = staticcall _stable_aggregator.stablecoin()
    STABLECOIN = stablecoin
    redeemable: address = stablecoin
    is_inverse: bool = False
    agg_price: uint256 = staticcall _stable_aggregator.price()
    factor: uint256 = agg_price
    if _stableswap.address != empty(address):
        coins: address[2] = [staticcall _stableswap.coins(0), staticcall _stableswap.coins(1)]
        redeemable = coins[0]
        if coins[0] == stablecoin:
            redeemable = coins[1]
            is_inverse = True
        else:
            assert coins[1] == stablecoin
        factor = self._factor(agg_price, staticcall _stableswap.price_oracle(), is_inverse)
    IS_INVERSE = is_inverse
    assert staticcall _pool.coins(0) == redeemable

    # --- Check and record if pool requires coin id in argument or not ---

    success: bool = False
    res: Bytes[32] = empty(Bytes[32])
    success, res = raw_call(
        _pool.address,
        abi_encode(empty(uint256), method_id=method_id("price_oracle(uint256)")),
        max_outsize=32, is_static_call=True, revert_on_failure=False)
    # Empty returndata means the pool has no price_oracle(uint256): either it
    # reverted, or its fallback swallowed the call (e.g. old ETH pools STOP on
    # an unknown selector, returning success with no data). Both mean the pool
    # only exposes the argument-less price_oracle().
    no_argument: bool = not success or len(res) == 0
    if no_argument:
        # A no-argument price_oracle() pool is 2-coin by construction,
        # so the only coin it prices is coin 1.
        assert _ix == 0, "Bad coin index"
    NO_ARGUMENT = no_argument

    # --- Check and record where the pool keeps the ma_time of its EMA ---

    success, res = raw_call(
        _pool.address,
        method_id("ma_exp_time()"),
        max_outsize=32, is_static_call=True, revert_on_failure=False)
    # Empty returndata means the pool has no ma_exp_time(), as above: a crypto
    # pool, which keeps ma_time in the low 64 bits of packed_rebalancing_params().
    PACKED_MA_TIME = not success or len(res) == 0

    WINDOW = _window
    TAU = _tau
    CAP = _cap
    STALE = _stale

    p_pool: uint256 = self._price_oracle()

    # Validate the oracle
    assert p_pool * factor // WAD > 0

    self.packed_band = self._pack_band(p_pool, p_pool, p_pool)
    self.packed_last = self._pack_last(block.timestamp, 1, p_pool, factor, block.timestamp)
    self.packed_obs[0] = self._pack_obs(block.timestamp, p_pool)


@internal
@pure
def _pack_band(_hi: uint256, _lo: uint256, _p: uint256) -> uint256:
    return (_hi << 170) | (_lo << 85) | _p


@internal
@pure
def _unpack_band(_packed: uint256) -> uint256[3]:
    return [_packed >> 170, (_packed >> 85) & (2**85 - 1), _packed & (2**85 - 1)]


@internal
@pure
def _pack_last(_t: uint256, _i: uint256, _p_pool: uint256, _factor: uint256, _t_factor: uint256) -> uint256:
    return (_t << 216) | (_i << 192) | (_p_pool << 104) | (_factor << 40) | _t_factor


@internal
@pure
def _pack_obs(_t: uint256, _p_block: uint256) -> uint256:
    return (_t << 88) | _p_block


@internal
@pure
def _factor(_agg_price: uint256, _p_stable_r: uint256, _is_inverse: bool) -> uint256:
    """
    @notice USD per unit of the pool's coin 0: (d_usd/d_st) / (d_usdt/d_st), as in CryptoWithStablePriceETH.
    """
    if _is_inverse:
        return unsafe_div(_agg_price * _p_stable_r, WAD)
    return _agg_price * WAD // _p_stable_r


@internal
@view
def _band(_packed_last: uint256) -> uint256[5]:
    """
    @notice The band brought to the current block.
    @param _packed_last packed_last as stored
    @return [hi, lo, p, p_block, p_pool], p_block = average block-end price of the pool since the last write,
            p_pool = current price_oracle of the pool; the pool is not read (p_pool = 0, p_block = price_oracle
            at that write) when the band was written in this block
    """
    band: uint256[3] = self._unpack_band(self.packed_band)
    dt: uint256 = unsafe_sub(block.timestamp, _packed_last >> 216)
    if dt == 0:
        return [band[0], band[1], band[2], (_packed_last >> 104) & (2**88 - 1), 0]

    # The pool EMA's own increment, inverted:
    # p_block = (p_pool - alpha * p_pool_last) / (1 - alpha), alpha = exp(-dt / ma_time)
    p_pool: uint256 = self._price_oracle()
    alpha_pool: uint256 = convert(math._wad_exp(-convert(unsafe_mul(dt, WAD) // self._ma_time(), int256)), uint256)
    p_block: uint256 = p_pool
    if alpha_pool < WAD - 10**6:
        p_pool_last: uint256 = (_packed_last >> 104) & (2**88 - 1)
        p_block = convert(
            max(convert(p_pool, int256) * SWAD - convert(alpha_pool * p_pool_last, int256), 0), uint256
        ) // unsafe_sub(WAD, alpha_pool)

    # Highest and lowest observation of the last WINDOW seconds, the one before them, and p_block;
    # once the last write is a whole WINDOW old, p_block alone covers the window
    p_max: uint256 = p_block
    p_min: uint256 = p_block
    t_prev: uint256 = 0
    p_prev: uint256 = 0
    t_start: uint256 = block.timestamp - WINDOW
    packed_obs: uint256[N_OBS // 2] = self.packed_obs
    for i: uint256 in range(N_OBS):
        observation: uint256 = packed_obs[i // 2] >> unsafe_mul(128, i % 2) & (2**128 - 1)
        if observation == 0:
            continue
        t: uint256 = observation >> 88
        p: uint256 = observation & (2**88 - 1)
        if t > t_start:
            p_max = max(p_max, p)
            p_min = min(p_min, p)
        elif t >= t_prev:
            t_prev = t
            p_prev = p
    if t_prev > 0 and dt < WINDOW:
        p_max = max(p_max, p_prev)
        p_min = min(p_min, p_prev)

    # hi and lo follow p_max and p_min with time constant TAU, at most CAP per 12 s;
    # a move never takes them past p_max or p_min
    alpha: uint256 = WAD - convert(math._wad_exp(-convert(unsafe_mul(dt, WAD) // TAU, int256)), uint256)
    max_move: uint256 = unsafe_div(CAP * dt, 12)
    hi: uint256 = band[0]
    lo: uint256 = band[1]
    if p_max > hi:
        hi = unsafe_add(hi, min(unsafe_div(unsafe_sub(p_max, hi) * alpha, WAD), unsafe_div(hi * max_move, WAD)))
    else:
        hi = unsafe_sub(hi, min(unsafe_div(unsafe_sub(hi, p_max) * alpha, WAD), unsafe_div(hi * max_move, WAD)))
    if p_min > lo:
        lo = unsafe_add(lo, min(unsafe_div(unsafe_sub(p_min, lo) * alpha, WAD), unsafe_div(lo * max_move, WAD)))
    else:
        lo = unsafe_sub(lo, min(unsafe_div(unsafe_sub(lo, p_min) * alpha, WAD), unsafe_div(lo * max_move, WAD)))
    return [hi, lo, min(max(band[2], lo), hi), p_block, p_pool]


@internal
@view
def _ma_time() -> uint256:
    """
    @notice Time constant of the pool's EMA: it decays as exp(-dt / ma_time).
            Read every time because the pool's admin can change it.
    """
    if PACKED_MA_TIME:
        return (staticcall POOL.packed_rebalancing_params()) & (2**64 - 1)
    return staticcall POOL.ma_exp_time()


@internal
@view
def _price_oracle() -> uint256:
    """
    @notice price_oracle of the pool: its EMA of block-end prices, decayed by the pool to now.
    """
    if NO_ARGUMENT:
        return staticcall POOL.price_oracle()
    return staticcall POOL.price_oracle(POOL_IX)


@internal
@view
def _factor_ro(_packed_last: uint256) -> uint256:
    """
    @notice USD per unit of the pool's coin 0 (the aggregator's price when coin 0 is crvUSD):
            as written last, or read afresh when that is older than STALE. Read afresh, the
            aggregator's price is the one it wrote last unless that is older than STALE too.
    """
    if unsafe_sub(block.timestamp, _packed_last & (2**40 - 1)) > STALE:
        agg_price: uint256 = 0
        if unsafe_sub(block.timestamp, staticcall STABLESWAP_AGGREGATOR.last_timestamp()) <= STALE:
            agg_price = staticcall STABLESWAP_AGGREGATOR.last_price()
        else:
            agg_price = staticcall STABLESWAP_AGGREGATOR.price()
        if STABLESWAP.address == empty(address):
            return agg_price
        return self._factor(agg_price, staticcall STABLESWAP.price_oracle(), IS_INVERSE)
    return (_packed_last >> 40) & (2**64 - 1)


@external
@view
def band() -> uint256[3]:
    """
    @notice Current [hi, lo, p] of the band in the pool's coin 0.
    @return [hi, lo, p], 1e18-scaled, before the conversion to USD.
    """
    band: uint256[5] = self._band(self.packed_last)
    return [band[0], band[1], band[2]]


@external
@view
def price() -> uint256:
    """
    @notice Price of the collateral in USD (1e18-scaled).
    @dev The band brought to the current block, without writing it.
    @return The price `price_w` returns in this block.
    """
    packed_last: uint256 = self.packed_last
    return unsafe_div(self._band(packed_last)[2] * self._factor_ro(packed_last), WAD)


@external
@view
def price_cached() -> uint256:
    """
    @notice Price as of the last write: no pool, stableswap or aggregator read;
            for callers who need the collateral's value only approximately.
    @return Price of the collateral in USD (1e18-scaled) at the last write.
    """
    return unsafe_div((self.packed_band & (2**85 - 1)) * ((self.packed_last >> 40) & (2**64 - 1)), WAD)


@internal
def _price_w() -> uint256:
    """
    @notice Bring the band to the current block and write it, with this block's observation.
    """
    packed_last: uint256 = self.packed_last
    band: uint256[5] = self._band(packed_last)
    factor: uint256 = (packed_last >> 40) & (2**64 - 1)
    t_factor: uint256 = packed_last & (2**40 - 1)
    if unsafe_sub(block.timestamp, t_factor) > STALE:
        if unsafe_sub(block.timestamp, staticcall STABLESWAP_AGGREGATOR.last_timestamp()) <= STALE:
            factor = staticcall STABLESWAP_AGGREGATOR.last_price()
        else:
            factor = extcall STABLESWAP_AGGREGATOR.price_w()
        if STABLESWAP.address != empty(address):
            factor = self._factor(factor, staticcall STABLESWAP.price_oracle(), IS_INVERSE)
        t_factor = block.timestamp
    if block.timestamp > packed_last >> 216:
        i: uint256 = (packed_last >> 192) & (2**24 - 1)
        packed_obs: uint256 = self.packed_obs[i // 2]
        if i % 2 == 0:
            packed_obs = (packed_obs & ((2**128 - 1) << 128)) | self._pack_obs(block.timestamp, band[3])
        else:
            packed_obs = (packed_obs & (2**128 - 1)) | (self._pack_obs(block.timestamp, band[3]) << 128)
        self.packed_band = self._pack_band(band[0], band[1], band[2])
        self.packed_obs[i // 2] = packed_obs
        self.packed_last = self._pack_last(block.timestamp, unsafe_add(i, 1) % N_OBS, band[4], factor, t_factor)
    return unsafe_div(band[2] * factor, WAD)


@external
def price_w() -> uint256:
    """
    @notice Same as `price`, but writes the band and this block's observation.
    @return Price of the collateral in USD (1e18-scaled).
    """
    return self._price_w()
