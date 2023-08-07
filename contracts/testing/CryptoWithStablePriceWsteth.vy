# @version 0.3.9
"""
@title CryptoWithStablePriceWsteth
@notice Price oracle for tricrypto+wsteth for crvUSD. Not limiting the price with chainlink - relying on tricrypto-ng
        With old tricrypto2 it is UNSAFE to use. Should be tricrypto-ng + steth-ng
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

interface wstETH:
    def stEthPerToken() -> uint256: view

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


TRICRYPTO: public(immutable(Tricrypto))
TRICRYPTO_IX: public(immutable(uint256))
STABLESWAP_AGGREGATOR: public(immutable(StableAggregator))
STABLESWAP: public(immutable(Stableswap))
STABLECOIN: public(immutable(address))
REDEEMABLE: public(immutable(address))
IS_INVERSE: immutable(bool)
FACTORY: public(immutable(ControllerFactory))

CHAINLINK_AGGREGATOR_ETH: immutable(ChainlinkAggregator)
CHAINLINK_PRICE_PRECISION_ETH: immutable(uint256)
CHAINLINK_AGGREGATOR_STETH: immutable(ChainlinkAggregator)
CHAINLINK_PRICE_PRECISION_STETH: immutable(uint256)
CHAINLINK_STALE_THRESHOLD: constant(uint256) = 86400
BOUND_SIZE: public(immutable(uint256))

STAKEDSWAP: public(immutable(Stableswap))
WSTETH: public(immutable(wstETH))

use_chainlink: public(bool)


@external
def __init__(
        tricrypto: Tricrypto,
        ix: uint256,
        stableswap: Stableswap,
        staked_swap: Stableswap,
        stable_aggregator: StableAggregator,
        factory: ControllerFactory,
        wsteth: wstETH,
        chainlink_aggregator_eth: ChainlinkAggregator,
        chainlink_aggregator_steth: ChainlinkAggregator,
        bound_size: uint256
    ):
    TRICRYPTO = tricrypto
    TRICRYPTO_IX = ix
    STABLESWAP_AGGREGATOR = stable_aggregator
    STABLESWAP = stableswap
    STAKEDSWAP = staked_swap
    FACTORY = factory
    WSTETH = wsteth
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

    self.use_chainlink = True
    CHAINLINK_AGGREGATOR_ETH = chainlink_aggregator_eth
    CHAINLINK_PRICE_PRECISION_ETH = 10**convert(chainlink_aggregator_eth.decimals(), uint256)
    CHAINLINK_AGGREGATOR_STETH = chainlink_aggregator_steth
    CHAINLINK_PRICE_PRECISION_STETH = 10**convert(chainlink_aggregator_steth.decimals(), uint256)
    BOUND_SIZE = bound_size


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
def staked_swap() -> Stableswap:
    return STAKEDSWAP


@external
@view
def stablecoin() -> address:
    return STABLECOIN


@external
@view
def redeemable() -> address:
    return REDEEMABLE


@internal
@view
def _raw_price() -> uint256:
    p_crypto_r: uint256 = TRICRYPTO.price_oracle(TRICRYPTO_IX)  # d_usdt/d_eth
    p_stable_r: uint256 = STABLESWAP.price_oracle()             # d_usdt/d_st
    p_stable_agg: uint256 = STABLESWAP_AGGREGATOR.price()       # d_usd/d_st
    if IS_INVERSE:
        p_stable_r = 10**36 / p_stable_r
    crv_p: uint256 = p_crypto_r * p_stable_agg / p_stable_r     # d_usd/d_eth

    use_chainlink: bool = self.use_chainlink

    # Limit ETH price
    if use_chainlink:
        chainlink_lrd: ChainlinkAnswer = CHAINLINK_AGGREGATOR_ETH.latestRoundData()
        if block.timestamp - min(chainlink_lrd.updated_at, block.timestamp) <= CHAINLINK_STALE_THRESHOLD:
            chainlink_p: uint256 = convert(chainlink_lrd.answer, uint256) * 10**18 / CHAINLINK_PRICE_PRECISION_ETH
            lower: uint256 = chainlink_p * (10**18 - BOUND_SIZE) / 10**18
            upper: uint256 = chainlink_p * (10**18 + BOUND_SIZE) / 10**18
            crv_p = min(max(crv_p, lower), upper)

    p_staked: uint256 = STAKEDSWAP.price_oracle()  # d_eth / d_steth

    # Limit STETH price
    if use_chainlink:
        chainlink_lrd: ChainlinkAnswer = CHAINLINK_AGGREGATOR_STETH.latestRoundData()
        if block.timestamp - min(chainlink_lrd.updated_at, block.timestamp) <= CHAINLINK_STALE_THRESHOLD:
            chainlink_p: uint256 = convert(chainlink_lrd.answer, uint256) * 10**18 / CHAINLINK_PRICE_PRECISION_STETH
            lower: uint256 = chainlink_p * (10**18 - BOUND_SIZE) / 10**18
            upper: uint256 = chainlink_p * (10**18 + BOUND_SIZE) / 10**18
            p_staked = min(max(p_staked, lower), upper)

    p_staked = min(p_staked, 10**18) * WSTETH.stEthPerToken() / 10**18  # d_eth / d_wsteth

    return p_staked * crv_p / 10**18


@external
@view
def raw_price() -> uint256:
    return self._raw_price()


@external
@view
def price() -> uint256:
    return self._raw_price()


@external
def price_w() -> uint256:
    return self._raw_price()


@external
def set_use_chainlink(do_it: bool):
    assert msg.sender == FACTORY.admin()
    self.use_chainlink = do_it
