# pragma version 0.4.3
"""
@title AggregatorStablePrice - aggregator of stablecoin prices for crvUSD
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2023 - all rights reserved
"""
# Returns price of stablecoin in "dollars" based on multiple redeemable stablecoins
# Recommended to use 3+ price sources
# Version3: Works with -ng pools
# Version4: Caps normalized TVL weights before computing the aggregate price,
#           and adds emergency_admin limited price pair removal

from snekmate.utils import math

interface Stableswap:
    def price_oracle(i: uint256=0) -> uint256: view
    def coins(i: uint256) -> address: view
    def get_virtual_price() -> uint256: view
    def totalSupply() -> uint256: view
    def D_oracle() -> uint256: view


struct PricePair:
    pool: Stableswap
    is_inverse: bool
    is_ng: bool


event AddPricePair:
    n: uint256
    pool: Stableswap
    is_inverse: bool

event RemovePricePair:
    n: uint256

event MovePricePair:
    n_from: uint256
    n_to: uint256

event SetAdmin:
    admin: address

event SetEmergencyAdmin:
    emergency_admin: address

event SetEmergencyRemoveCount:
    emergency_remove_count: uint256

event SetShareCap:
    share_cap: uint256


MAX_PAIRS: constant(uint256) = 20
MIN_LIQUIDITY: constant(uint256) = 100_000 * 10**18  # Only take into account pools with enough liquidity
WAD: constant(uint256) = 10**18

STABLECOIN: immutable(address)
SIGMA: immutable(uint256)
price_pairs: public(PricePair[MAX_PAIRS])
n_price_pairs: uint256

last_timestamp: public(uint256)
last_tvl: public(uint256[MAX_PAIRS])
TVL_MA_TIME: public(constant(uint256)) = 50000  # s
last_price: public(uint256)
custom_share_cap: public(uint256)

admin: public(address)
emergency_admin: public(address)
emergency_remove_count: public(uint256)


@deploy
def __init__(stablecoin: address, sigma: uint256, admin: address, emergency_admin: address):
    STABLECOIN = stablecoin
    SIGMA = sigma  # The change is so rare that we can change the whole thing altogether
    self.admin = admin
    self.emergency_admin = emergency_admin
    self.last_price = WAD
    self.last_timestamp = block.timestamp


@external
@view
def sigma() -> uint256:
    return SIGMA


@external
@view
def stablecoin() -> address:
    return STABLECOIN


@internal
@pure
def _default_cap(n_active: uint256) -> uint256:
    if n_active <= 1:
        return WAD
    elif n_active == 2:
        return 70 * (WAD // 100)  # 0.7
    elif n_active <= 5:
        return 45 * (WAD // 100)  # 0.45
    else:
        return 24 * (WAD // 100)  # 0.24


@internal
@view
def _share_cap(n_active: uint256) -> uint256:
    max_share: uint256 = self.custom_share_cap
    if max_share == 0:
        max_share = self._default_cap(n_active)
    return max_share


@internal
@view
def _ema_tvl() -> DynArray[uint256, MAX_PAIRS]:
    tvls: DynArray[uint256, MAX_PAIRS] = []
    last_timestamp: uint256 = self.last_timestamp

    # alpha = exp(-dt / TVL_MA_TIME), WAD-scaled.
    # EMA = current_tvl * (1 - alpha) + last_tvl * alpha.
    alpha: uint256 = WAD
    if last_timestamp < block.timestamp:
        dt: uint256 = block.timestamp - last_timestamp
        alpha = convert(math._wad_exp(-convert(dt * WAD // TVL_MA_TIME, int256)), uint256)
    n_price_pairs: uint256 = self.n_price_pairs

    for i: uint256 in range(n_price_pairs, bound=MAX_PAIRS):
        price_pair: PricePair = self.price_pairs[i]
        tvl: uint256 = 0
        if price_pair.is_ng:
            tvl = staticcall price_pair.pool.D_oracle()
        else:
            tvl = self.last_tvl[i]
            if alpha != WAD:
                new_tvl: uint256 = (staticcall price_pair.pool.totalSupply()) * WAD //\
                    (staticcall price_pair.pool.get_virtual_price())
                tvl = (new_tvl * (WAD - alpha) + tvl * alpha) // WAD
        tvls.append(tvl)

    return tvls


@internal
@view
def _get_p(price_pair: PricePair) -> uint256:
    p: uint256 = 0
    if price_pair.is_ng:
        p = staticcall price_pair.pool.price_oracle(0)
    else:
        p = staticcall price_pair.pool.price_oracle()
    if price_pair.is_inverse:
        p = 10**36 // p
    return p


@internal
@pure
def _n_active_sources(tvls: DynArray[uint256, MAX_PAIRS], n: uint256) -> uint256:
    n_active: uint256 = 0
    for i: uint256 in range(n, bound=MAX_PAIRS):
        if tvls[i] >= MIN_LIQUIDITY:
            n_active += 1
    return n_active


@internal
@view
def _active_sources(tvls: DynArray[uint256, MAX_PAIRS], n: uint256) -> (
    uint256[MAX_PAIRS],
    uint256[MAX_PAIRS],
    uint256,
    uint256
):
    prices: uint256[MAX_PAIRS] = empty(uint256[MAX_PAIRS])
    D: uint256[MAX_PAIRS] = empty(uint256[MAX_PAIRS])
    Dsum: uint256 = 0
    n_active: uint256 = 0
    for i: uint256 in range(n, bound=MAX_PAIRS):
        price_pair: PricePair = self.price_pairs[i]
        pool_supply: uint256 = tvls[i]

        # Only sufficiently deep pools participate in price aggregation.
        if pool_supply >= MIN_LIQUIDITY:
            prices[i] = self._get_p(price_pair)
            D[i] = pool_supply
            Dsum += pool_supply
            n_active += 1

    return prices, D, Dsum, n_active


@internal
@view
def _capped_weights(
    D: uint256[MAX_PAIRS],
    Dsum: uint256,
    n_active: uint256,
    n: uint256
) -> uint256[MAX_PAIRS]:
    max_share: uint256 = self._share_cap(n_active)

    # Water-filling with an upper cap:
    #   weight[i] = min(max_share, D[i] * remaining_share / remaining_Dsum)
    # Each pass fixes newly capped sources, then redistributes the remaining
    # share over the still-uncapped liquidity.
    weights: uint256[MAX_PAIRS] = empty(uint256[MAX_PAIRS])
    remaining_Dsum: uint256 = Dsum
    remaining_share: uint256 = WAD

    # At most floor((WAD - 1) / max_share) sources can be capped before
    # the remaining share is <= max_share. Add one pass to detect that no
    # more caps are needed. n_active is also an upper bound: each successful
    # pass caps at least one active source.
    max_passes: uint256 = min(n_active, unsafe_div(WAD - 1, max_share) + 1)
    for _: uint256 in range(max_passes, bound=MAX_PAIRS):
        did_cap: bool = False
        for i: uint256 in range(n, bound=MAX_PAIRS):
            if weights[i] == 0:
                candidate_share: uint256 = unsafe_div(remaining_share * D[i], remaining_Dsum)
                if candidate_share > max_share:
                    weights[i] = max_share
                    remaining_Dsum -= D[i]
                    remaining_share -= max_share
                    did_cap = True
        if not did_cap:
            break

    for i: uint256 in range(n, bound=MAX_PAIRS):
        if weights[i] == 0:
            weights[i] = unsafe_div(remaining_share * D[i], remaining_Dsum)

    return weights


@internal
@pure
def _weighted_avg(
    prices: uint256[MAX_PAIRS],
    weights: uint256[MAX_PAIRS],
    n: uint256
) -> uint256:
    # sum(weights[i] * prices[i]) / sum(weights[i])
    weighted_sum: uint256 = 0
    weight_sum: uint256 = 0
    for i: uint256 in range(n, bound=MAX_PAIRS):
        weighted_sum += weights[i] * prices[i]
        weight_sum += weights[i]
    return weighted_sum // weight_sum


@internal
@view
def _weighted_price(
    prices: uint256[MAX_PAIRS],
    weights: uint256[MAX_PAIRS],
    p_avg: uint256,
    n: uint256
) -> uint256:
    # Penalize sources according to squared distance from the capped-weight
    # average:
    #   e[i] = ((p[i] - p_avg) / sigma) ** 2
    #   exp_weight[i] = weight[i] * exp(-(e[i] - min(e)))
    # Subtracting min(e) keeps the largest exponential at 1.0 and avoids
    # underweighting every source when all prices are far from p_avg.
    e: uint256[MAX_PAIRS] = empty(uint256[MAX_PAIRS])
    e_min: uint256 = max_value(uint256)
    for i: uint256 in range(n, bound=MAX_PAIRS):
        if weights[i] != 0:
            p: uint256 = prices[i]
            price_delta: uint256 = max(p, p_avg) - min(p, p_avg)
            e[i] = price_delta**2 // (SIGMA**2 // WAD)
            e_min = min(e[i], e_min)
    exp_weights: uint256[MAX_PAIRS] = empty(uint256[MAX_PAIRS])
    for i: uint256 in range(n, bound=MAX_PAIRS):
        if weights[i] != 0:
            exp_weights[i] = weights[i] * convert(
                math._wad_exp(-convert(e[i] - e_min, int256)),
                uint256
            ) // WAD
    return self._weighted_avg(prices, exp_weights, n)


@internal
@view
def _price(tvls: DynArray[uint256, MAX_PAIRS]) -> uint256:
    n: uint256 = self.n_price_pairs
    prices: uint256[MAX_PAIRS] = empty(uint256[MAX_PAIRS])
    D: uint256[MAX_PAIRS] = empty(uint256[MAX_PAIRS])
    Dsum: uint256 = 0
    n_active: uint256 = 0
    prices, D, Dsum, n_active = self._active_sources(tvls, n)
    if Dsum == 0:
        return WAD  # Placeholder for no active pools

    weights: uint256[MAX_PAIRS] = self._capped_weights(D, Dsum, n_active, n)
    p_avg: uint256 = self._weighted_avg(prices, weights, n)
    return self._weighted_price(prices, weights, p_avg, n)


@external
@pure
def default_cap(n_active: uint256) -> uint256:
    return self._default_cap(n_active)


@external
@view
def share_cap() -> uint256:
    return self._share_cap(self._n_active_sources(self._ema_tvl(), self.n_price_pairs))


@external
@view
def ema_tvl() -> DynArray[uint256, MAX_PAIRS]:
    return self._ema_tvl()


@external
@view
def price() -> uint256:
    return self._price(self._ema_tvl())


@external
def price_w() -> uint256:
    if self.last_timestamp == block.timestamp:
        return self.last_price
    else:
        ema_tvl: DynArray[uint256, MAX_PAIRS] = self._ema_tvl()
        self.last_timestamp = block.timestamp
        for i: uint256 in range(len(ema_tvl), bound=MAX_PAIRS):
            self.last_tvl[i] = ema_tvl[i]
        p: uint256 = self._price(ema_tvl)
        self.last_price = p
        return p


@external
def add_price_pair(_pool: Stableswap):
    assert msg.sender == self.admin
    price_pair: PricePair = empty(PricePair)
    price_pair.pool = _pool
    success: bool = raw_call(
        _pool.address, abi_encode(convert(0, uint256), method_id=method_id("price_oracle(uint256)")),
        revert_on_failure=False
    )
    if success:
        price_pair.is_ng = True
    coins: address[2] = [staticcall _pool.coins(0), staticcall _pool.coins(1)]
    if coins[0] == STABLECOIN:
        price_pair.is_inverse = True
    else:
        assert coins[1] == STABLECOIN
    n: uint256 = self.n_price_pairs
    self.price_pairs[n] = price_pair  # Should revert if too many pairs
    self.last_tvl[n] = staticcall _pool.totalSupply()
    self.n_price_pairs = n + 1
    log AddPricePair(n=n, pool=_pool, is_inverse=price_pair.is_inverse)


@external
def remove_price_pair(n: uint256):
    if msg.sender == self.emergency_admin:
        self.emergency_remove_count -= 1  # Revert if zero
    else:
        assert msg.sender == self.admin

    n_max: uint256 = self.n_price_pairs - 1
    assert n <= n_max

    if n < n_max:
        self.price_pairs[n] = self.price_pairs[n_max]
        self.last_tvl[n] = self.last_tvl[n_max]
        log MovePricePair(n_from=n_max, n_to=n)
    self.n_price_pairs = n_max
    log RemovePricePair(n=n)


@external
def set_share_cap(_share_cap: uint256):
    assert msg.sender == self.admin
    assert _share_cap <= WAD
    self.custom_share_cap = _share_cap
    log SetShareCap(share_cap=_share_cap)


@external
def set_admin(_admin: address):
    # We are not doing commit / apply because the owner will be a voting DAO anyway
    # which has vote delays
    assert msg.sender == self.admin
    self.admin = _admin
    log SetAdmin(admin=_admin)


@external
def set_emergency_admin(_emergency_admin: address):
    assert msg.sender == self.admin
    self.emergency_admin = _emergency_admin
    log SetEmergencyAdmin(emergency_admin=_emergency_admin)


@external
def set_emergency_remove_count(_emergency_remove_count: uint256):
    assert msg.sender == self.admin
    self.emergency_remove_count = _emergency_remove_count
    log SetEmergencyRemoveCount(emergency_remove_count=_emergency_remove_count)
