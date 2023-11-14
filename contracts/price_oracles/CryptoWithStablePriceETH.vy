# @version 0.3.9
"""
@title CryptoWithStablePriceETH
@notice Price oracle for tricrypto for crvUSD. Optional Chainlink included
        With old tricrypto2 it is UNSAFE to use. Should be tricrypto-ng only
@author Curve.Fi
@license MIT
"""

# Tricrypto-ng
interface Tricrypto:
    def price_oracle(k: uint256) -> uint256: view
    def coins(i: uint256) -> address: view
    def totalSupply() -> uint256: view
    def virtual_price() -> uint256: view

interface StableAggregator:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable
    def stablecoin() -> address: view

interface Stableswap:
    def price_oracle() -> uint256: view
    def coins(i: uint256) -> address: view

interface ControllerFactory:
    def admin() -> address: view


struct ChainlinkAnswer:
    round_id: uint80
    answer: int256
    started_at: uint256
    updated_at: uint256
    answered_in_round: uint80

interface ChainlinkAggregator:
    def latestRoundData() -> ChainlinkAnswer: view
    def decimals() -> uint8: view


N_POOLS: public(constant(uint256)) = 2

TRICRYPTO: public(immutable(Tricrypto[N_POOLS]))
TRICRYPTO_IX: public(immutable(uint256[N_POOLS]))
STABLESWAP_AGGREGATOR: public(immutable(StableAggregator))
STABLESWAP: public(immutable(Stableswap[N_POOLS]))
STABLECOIN: public(immutable(address))
REDEEMABLE: public(immutable(address[N_POOLS]))
IS_INVERSE: immutable(bool[N_POOLS])
FACTORY: public(immutable(ControllerFactory))

CHAINLINK_AGGREGATOR_ETH: immutable(ChainlinkAggregator)
CHAINLINK_PRICE_PRECISION_ETH: immutable(uint256)
CHAINLINK_STALE_THRESHOLD: constant(uint256) = 86400
BOUND_SIZE: public(immutable(uint256))

use_chainlink: public(bool)

last_tvl: public(uint256[N_POOLS])
last_timestamp: public(uint256)
TVL_MA_TIME: public(constant(uint256)) = 50000  # s


@external
def __init__(
        tricrypto: Tricrypto[N_POOLS],
        ix: uint256[N_POOLS],             # 1 = ETH
        stableswap: Stableswap[N_POOLS],
        stable_aggregator: StableAggregator,
        factory: ControllerFactory,
        chainlink_aggregator_eth: ChainlinkAggregator,
        bound_size: uint256  # 1.5% sounds ok before we turn it off
    ):
    TRICRYPTO = tricrypto
    TRICRYPTO_IX = ix
    STABLESWAP_AGGREGATOR = stable_aggregator
    STABLESWAP = stableswap
    FACTORY = factory
    _stablecoin: address = stable_aggregator.stablecoin()
    STABLECOIN = _stablecoin
    _redeemable: address[N_POOLS] = empty(address[N_POOLS])
    _is_inverse: bool[N_POOLS] = empty(bool[N_POOLS])
    for i in range(N_POOLS):
        coins: address[2] = [stableswap[i].coins(0), stableswap[i].coins(1)]
        if coins[0] == _stablecoin:
            _redeemable[i] = coins[1]
            _is_inverse[i] = True
        else:
            _redeemable[i] = coins[0]
            _is_inverse[i] = False
            assert coins[1] == _stablecoin
        assert tricrypto[i].coins(0) == _redeemable[i]
        self.last_tvl[i] = tricrypto[i].totalSupply() * tricrypto[i].virtual_price() / 10**18
    IS_INVERSE = _is_inverse
    REDEEMABLE = _redeemable

    self.use_chainlink = True
    CHAINLINK_AGGREGATOR_ETH = chainlink_aggregator_eth
    CHAINLINK_PRICE_PRECISION_ETH = 10**convert(chainlink_aggregator_eth.decimals(), uint256)
    BOUND_SIZE = bound_size


@internal
@pure
def exp(power: int256) -> uint256:
    if power <= -42139678854452767551:
        return 0

    if power >= 135305999368893231589:
        raise "exp overflow"

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
def _ema_tvl() -> uint256[N_POOLS]:
    last_timestamp: uint256 = self.last_timestamp
    last_tvl: uint256[N_POOLS] = self.last_tvl

    if last_timestamp < block.timestamp:
        alpha: uint256 = self.exp(- convert((block.timestamp - last_timestamp) * 10**18 / TVL_MA_TIME, int256))
        # alpha = 1.0 when dt = 0
        # alpha = 0.0 when dt = inf
        for i in range(N_POOLS):
            tvl: uint256 = TRICRYPTO[i].totalSupply() * TRICRYPTO[i].virtual_price() / 10**18
            last_tvl[i] = (tvl * (10**18 - alpha) + last_tvl[i] * alpha) / 10**18

    return last_tvl


@external
@view
def ema_tvl() -> uint256[N_POOLS]:
    return self._ema_tvl()


@internal
@view
def _raw_price(tvls: uint256[N_POOLS], agg_price: uint256) -> uint256:
    weighted_price: uint256 = 0
    weights: uint256 = 0
    for i in range(N_POOLS):
        p_crypto_r: uint256 = TRICRYPTO[i].price_oracle(TRICRYPTO_IX[i])   # d_usdt/d_eth
        p_stable_r: uint256 = STABLESWAP[i].price_oracle()                 # d_usdt/d_st
        p_stable_agg: uint256 = agg_price                                  # d_usd/d_st
        if IS_INVERSE[i]:
            p_stable_r = 10**36 / p_stable_r
        weight: uint256 = tvls[i]
        # Prices are already EMA but weights - not so much
        weights += weight
        weighted_price += p_crypto_r * p_stable_agg / p_stable_r * weight     # d_usd/d_eth
    crv_p: uint256 = weighted_price / weights

    # Limit BTC price
    if self.use_chainlink:
        chainlink_lrd: ChainlinkAnswer = CHAINLINK_AGGREGATOR_ETH.latestRoundData()
        if block.timestamp - min(chainlink_lrd.updated_at, block.timestamp) <= CHAINLINK_STALE_THRESHOLD:
            chainlink_p: uint256 = convert(chainlink_lrd.answer, uint256) * 10**18 / CHAINLINK_PRICE_PRECISION_ETH
            lower: uint256 = chainlink_p * (10**18 - BOUND_SIZE) / 10**18
            upper: uint256 = chainlink_p * (10**18 + BOUND_SIZE) / 10**18
            crv_p = min(max(crv_p, lower), upper)

    return crv_p


@external
@view
def raw_price() -> uint256:
    return self._raw_price(self._ema_tvl(), STABLESWAP_AGGREGATOR.price())


@external
@view
def price() -> uint256:
    return self._raw_price(self._ema_tvl(), STABLESWAP_AGGREGATOR.price())


@external
def price_w() -> uint256:
    tvls: uint256[N_POOLS] = self._ema_tvl()
    if self.last_timestamp < block.timestamp:
        self.last_timestamp = block.timestamp
        self.last_tvl = tvls
    return self._raw_price(tvls, STABLESWAP_AGGREGATOR.price_w())


@external
def set_use_chainlink(do_it: bool):
    assert msg.sender == FACTORY.admin()
    self.use_chainlink = do_it
