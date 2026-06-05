# pragma version 0.4.3
"""
@title AggregatorStablePrice - aggregator of stablecoin prices for crvUSD
@author Curve Finance
@license MIT
@dev The emergency admin can remove a limited number of price sources. The
     limit is set by admin via `set_emergency_remove_count`.
"""
# Returns price of stablecoin in "dollars" based on multiple redeemable stablecoins
# Recommended to use 3+ price sources
# Version3: Works with -ng pools
# Version4: Caps relative TVL weights before computing the aggregate price,
#           and adds emergency_admin limited price pair removal

from snekmate.utils import math

from aggregate_stable_price import capped_share
from aggregate_stable_price import weighted_price
initializes: capped_share
initializes: weighted_price
exports: (
    capped_share.custom_share_cap,
    capped_share.default_cap,
    weighted_price.sigma,
)

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

MAX_PAIRS: constant(uint256) = 20
MAX_N: constant(uint256) = 64
MIN_LIQUIDITY: constant(uint256) = 100_000 * 10**18  # Only take into account pools with enough liquidity
WAD: constant(uint256) = 10**18

STABLECOIN: immutable(address)
price_pairs: public(PricePair[MAX_PAIRS])
n_price_pairs: uint256

last_timestamp: public(uint256)
last_tvl: public(uint256[MAX_PAIRS])
TVL_MA_TIME: public(constant(uint256)) = 50000  # s
last_price: public(uint256)

admin: public(address)
emergency_admin: public(address)
emergency_remove_count: public(uint256)


@deploy
def __init__(_stablecoin: address, _sigma: uint256, _admin: address, _emergency_admin: address):
    """
    @notice Contract constructor.
    @param _stablecoin Stablecoin whose price is aggregated by this oracle.
    @param _sigma Width parameter for exponential price-source penalty.
    @param _admin Address allowed to manage sources and parameters.
    @param _emergency_admin Address of the emergency role.
    """
    assert _stablecoin != empty(address), "zero stablecoin"
    STABLECOIN = _stablecoin
    weighted_price.__init__(_sigma)
    assert _admin != empty(address), "zero admin"  # Needed to set up the oracle
    self.admin = _admin
    self.emergency_admin = _emergency_admin

    self.last_price = WAD
    self.last_timestamp = block.timestamp


@external
@view
def stablecoin() -> address:
    """
    @notice Stablecoin address used by the aggregator.
    @return Stablecoin address.
    """
    return STABLECOIN


@internal
@view
def _ema_tvl() -> DynArray[uint256, MAX_PAIRS]:
    """
    @dev Compute current TVL values with EMA smoothing for non-NG pools.
    @return TVLs aligned to configured price-pair slots.
    """
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
                new_tvl: uint256 = (staticcall price_pair.pool.totalSupply()) *\
                    (staticcall price_pair.pool.get_virtual_price()) // WAD
                tvl = (new_tvl * (WAD - alpha) + tvl * alpha) // WAD
        tvls.append(tvl)

    return tvls


@internal
@view
def _get_p(price_pair: PricePair) -> uint256:
    """
    @dev Read a pool oracle price.
    @param price_pair Pool metadata.
    @return WAD-scaled stablecoin price.
    """
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
def _n_active_sources(tvls: DynArray[uint256, MAX_PAIRS]) -> uint256:
    """
    @dev Count TVL entries above the minimum liquidity threshold.
    @param tvls TVL values aligned to configured price-pair slots.
    @return Number of active sources.
    """
    n_active: uint256 = 0
    for tvl: uint256 in tvls:
        if tvl >= MIN_LIQUIDITY:
            n_active += 1
    return n_active


@internal
@view
def _active_sources(tvls: DynArray[uint256, MAX_PAIRS]) -> (
    DynArray[uint256, MAX_PAIRS],
    DynArray[uint256, MAX_PAIRS]
):
    """
    @dev Collect compact arrays of prices and TVLs for active sources only.
    @param tvls TVL values aligned to price-pair slots.
    @return Active source prices.
    @return Active source TVLs.
    """
    prices: DynArray[uint256, MAX_PAIRS] = []
    D: DynArray[uint256, MAX_PAIRS] = []
    for i: uint256 in range(len(tvls), bound=MAX_PAIRS):
        # Only sufficiently deep pools participate in price aggregation.
        if tvls[i] >= MIN_LIQUIDITY:
            prices.append(self._get_p(self.price_pairs[i]))
            D.append(tvls[i])

    return prices, D


@internal
@view
def _price(tvls: DynArray[uint256, MAX_PAIRS]) -> uint256:
    """
    @dev Aggregate prices from active sources using capped TVL weights and
         exponential deviation penalty.
    @param tvls TVL values aligned to price-pair slots.
    @return Aggregated WAD-scaled stablecoin price.
    """
    prices: DynArray[uint256, MAX_PAIRS] = []
    D: DynArray[uint256, MAX_PAIRS] = []
    prices, D = self._active_sources(tvls)
    if len(D) == 0:
        return WAD  # Placeholder for no active pools

    # Limit impact of a single source by capping its relative share.
    weights: DynArray[uint256, MAX_N] = capped_share.capped_weights(D)
    # Take weighted average price as reference.
    p_ref: uint256 = weighted_price.weighted_avg(prices, weights)
    # Penalize price sources according to the selected reference price.
    return weighted_price.exp_penalized_price(prices, weights, p_ref)


@external
@view
def share_cap() -> uint256:
    """
    @notice Return the share cap currently used for active sources.
    @return Custom cap if set, otherwise the default cap for current active count.
    """
    return capped_share.share_cap(self._n_active_sources(self._ema_tvl()))


@external
@view
def ema_tvl() -> DynArray[uint256, MAX_PAIRS]:
    """
    @notice Compute current EMA TVL values without updating storage.
    @return TVL values aligned to price-pair slots.
    """
    return self._ema_tvl()


@external
@view
def price() -> uint256:
    """
    @notice Compute the aggregated price without updating storage.
    @return WAD-scaled stablecoin price.
    """
    return self._price(self._ema_tvl())


@external
def price_w() -> uint256:
    """
    @notice Compute the aggregated price and checkpoint EMA TVLs.
    @return WAD-scaled stablecoin price.
    """
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
    """
    @notice Add a pool as a price source.
    @param _pool StableSwap pool containing the configured stablecoin.
    """
    assert msg.sender == self.admin, "only admin"
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
        assert coins[1] == STABLECOIN, "not stablecoin pair"
    n: uint256 = self.n_price_pairs
    self.price_pairs[n] = price_pair  # dev: too many pairs
    self.last_tvl[n] = staticcall _pool.totalSupply()
    self.n_price_pairs = n + 1
    log AddPricePair(n=n, pool=_pool, is_inverse=price_pair.is_inverse)


@external
def remove_price_pair(n: uint256):
    """
    @notice Remove a price source by index.
    @dev Admin can remove without limit; emergency admin consumes one removal.
    @param n Index of the price source to remove.
    """
    if msg.sender == self.admin:
        # Checking admin first, so admin==emergency_admin case
        # does not create issues with remove counter
        pass
    else:
        assert msg.sender == self.emergency_admin, "only admin"
        self.emergency_remove_count -= 1  # dev: no emergency removals

    n_max: uint256 = self.n_price_pairs - 1  # dev: no pairs to remove
    assert n <= n_max, "bad pair index"

    if n < n_max:
        self.price_pairs[n] = self.price_pairs[n_max]
        self.last_tvl[n] = self.last_tvl[n_max]
        log MovePricePair(n_from=n_max, n_to=n)
    self.n_price_pairs = n_max
    log RemovePricePair(n=n)


@external
def set_share_cap(_share_cap: uint256):
    """
    @notice Set a custom per-source share cap.
    @param _share_cap WAD-scaled cap value.
    """
    assert msg.sender == self.admin, "only admin"
    capped_share.set_custom_share_cap(_share_cap)


@external
def set_admin(_admin: address):
    """
    @notice Set the admin address.
    @param _admin New admin address.
    """
    assert msg.sender == self.admin, "only admin"
    self.admin = _admin
    log SetAdmin(admin=_admin)


@external
def set_emergency_admin(_emergency_admin: address):
    """
    @notice Set the emergency admin address.
    @param _emergency_admin New emergency admin address.
    """
    assert msg.sender == self.admin, "only admin"
    self.emergency_admin = _emergency_admin
    log SetEmergencyAdmin(emergency_admin=_emergency_admin)


@external
def set_emergency_remove_count(_emergency_remove_count: uint256):
    """
    @notice Set how many sources the emergency admin may remove.
    @param _emergency_remove_count Number of permitted emergency removals.
    """
    assert msg.sender == self.admin, "only admin"
    self.emergency_remove_count = _emergency_remove_count
    log SetEmergencyRemoveCount(emergency_remove_count=_emergency_remove_count)
