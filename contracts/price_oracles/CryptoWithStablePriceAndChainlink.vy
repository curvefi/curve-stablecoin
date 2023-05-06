# @version 0.3.7
"""
@title CryptoWithStablePriceAndChainlink - price oracle for tricrypto with Chainlink limits for crvUSD
@author Curve.Fi
@license MIT
"""

interface Tricrypto:
    def price_oracle(k: uint256) -> uint256: view
    def coins(i: uint256) -> address: view

interface StableAggregator:
    def price() -> uint256: view
    def stablecoin() -> address: view

interface Stableswap:
    def price_oracle() -> uint256: view
    def coins(i: uint256) -> address: view

interface ChainlinkAggregator:
    # Returns: (roundId, answer, startedAt, updatedAt, answeredInRound)
    # answer
    # is the answer for the given round
    # answeredInRound
    # is the round ID of the round in which the answer was computed. (Only some AggregatorV3Interface implementations return meaningful values)
    # roundId
    # is the round ID from the aggregator for which the data was retrieved combined with a phase to ensure that round IDs get larger as time moves forward.
    # startedAt
    # is the timestamp when the round was started. (Only some AggregatorV3Interface implementations return meaningful values)
    # updatedAt
    # is the timestamp when the round last was updated (i.e. answer was last computed)
    def latestRoundData() -> (uint80, int256, uint256, uint256, uint80): view
    def decimals() -> uint8: view


TRICRYPTO: immutable(Tricrypto)
TRICRYPTO_IX: immutable(uint256)
STABLESWAP_AGGREGATOR: immutable(StableAggregator)
STABLESWAP: immutable(Stableswap)
STABLECOIN: immutable(address)
REDEEMABLE: immutable(address)
IS_INVERSE: immutable(bool)
MA_EXP_TIME: immutable(uint256)

MIN_MA_EXP_TIME: constant(uint256) = 30
MAX_MA_EXP_TIME: constant(uint256) = 365 * 86400

last_price: public(uint256)
last_timestamp: public(uint256)

CHAINLINK_AGGREGATOR: immutable(ChainlinkAggregator)
CHAINLINK_PRICE_PRECISION: immutable(uint256)
BOUND_SIZE: immutable(uint256)  # boudaries are in %


@external
def __init__(
        tricrypto: Tricrypto, ix: uint256, stableswap: Stableswap, stable_aggregator: StableAggregator,
        chainlink_aggregator: ChainlinkAggregator, ma_exp_time: uint256, bound_size: uint256
    ):
    TRICRYPTO = tricrypto
    TRICRYPTO_IX = ix
    STABLESWAP_AGGREGATOR = stable_aggregator
    STABLESWAP = stableswap
    _stablecoin: address = stable_aggregator.stablecoin()
    _redeemable: address = empty(address)
    STABLECOIN = _stablecoin
    coins: address[2] = [stableswap.coins(0), stableswap.coins(1)]
    is_inverse: bool = False
    if coins[0] == _stablecoin:
        _redeemable = coins[1]
        is_inverse = True
    else:
        _redeemable = coins[0]
        assert coins[1] == _stablecoin
    IS_INVERSE = is_inverse
    REDEEMABLE = _redeemable
    assert tricrypto.coins(0) == _redeemable

    assert ma_exp_time <= MAX_MA_EXP_TIME
    assert ma_exp_time >= MIN_MA_EXP_TIME
    MA_EXP_TIME = ma_exp_time

    CHAINLINK_AGGREGATOR = chainlink_aggregator
    CHAINLINK_PRICE_PRECISION = 10**convert(chainlink_aggregator.decimals(), uint256)

    BOUND_SIZE = bound_size


@internal
@view
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


@external
@view
def tricrypto() -> Tricrypto:
    return TRICRYPTO


@external
@view
def stableswap_aggregator() -> StableAggregator:
    return STABLESWAP_AGGREGATOR


@external
@view
def stableswap() -> Stableswap:
    return STABLESWAP


@external
@view
def stablecoin() -> address:
    return STABLECOIN


@external
@view
def redeemable() -> address:
    return REDEEMABLE


@external
@view
def ma_exp_time() -> uint256:
    return MA_EXP_TIME


@internal
@view
def _raw_price() -> uint256:
    p_crypto_r: uint256 = TRICRYPTO.price_oracle(TRICRYPTO_IX)  # d_usdt/d_eth
    p_stable_r: uint256 = STABLESWAP.price_oracle()             # d_usdt/d_st
    p_stable_agg: uint256 = STABLESWAP_AGGREGATOR.price()       # d_usd/d_st
    if IS_INVERSE:
        p_stable_r = 10**36 / p_stable_r
    crv_p: uint256 = p_crypto_r * p_stable_agg / p_stable_r     # d_usd/d_eth

    chainlink_lrd: (uint80, int256, uint256, uint256, uint80) = CHAINLINK_AGGREGATOR.latestRoundData()
    chainlink_p: uint256 = convert(chainlink_lrd[1], uint256) * 10**18 / CHAINLINK_PRICE_PRECISION

    lower: uint256 = chainlink_p * (100 - BOUND_SIZE) / 100
    if lower > crv_p:
        return lower

    upper: uint256 = chainlink_p * (100 + BOUND_SIZE) / 100
    if upper < crv_p:
        return upper

    return crv_p


@external
@view
def raw_price() -> uint256:
    return self._raw_price()


@internal
@view
def ema_price() -> uint256:
    last_timestamp: uint256 = self.last_timestamp
    last_price: uint256 = self.last_price

    if last_timestamp == 0:
        return self._raw_price()

    if last_timestamp < block.timestamp:
        current_price: uint256 = self._raw_price()
        alpha: uint256 = self.exp(- convert((block.timestamp - last_timestamp) * 10**18 / MA_EXP_TIME, int256))
        return (current_price * (10**18 - alpha) + last_price * alpha) / 10**18

    else:
        return last_price


@external
@view
def price() -> uint256:
    return self.ema_price()


@external
def price_w() -> uint256:
    p: uint256 = self.ema_price()
    if self.last_timestamp < block.timestamp:
        self.last_price = p
        self.last_timestamp = block.timestamp
    return p
