# @version 0.3.10
"""
@title CryptoWithStablePriceTBTC
@notice Price oracle for tricryptoLLAMA for crvUSD. Optional Chainlink included
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
STABLECOIN: public(immutable(address))
FACTORY: public(immutable(ControllerFactory))

CHAINLINK_AGGREGATOR_BTC: immutable(ChainlinkAggregator)
CHAINLINK_PRICE_PRECISION_BTC: immutable(uint256)
CHAINLINK_STALE_THRESHOLD: constant(uint256) = 86400
BOUND_SIZE: public(immutable(uint256))

use_chainlink: public(bool)


@external
def __init__(
        tricrypto: Tricrypto,
        ix: uint256,             # 0 = TBTC
        stable_aggregator: StableAggregator,
        factory: ControllerFactory,
        chainlink_aggregator_btc: ChainlinkAggregator,
        bound_size: uint256  # 1.5% sounds ok before we turn it off
    ):
    TRICRYPTO = tricrypto
    TRICRYPTO_IX = ix
    STABLESWAP_AGGREGATOR = stable_aggregator
    FACTORY = factory
    _stablecoin: address = stable_aggregator.stablecoin()
    STABLECOIN = _stablecoin
    assert tricrypto.coins(0) == _stablecoin  # First coin is crvUSD

    self.use_chainlink = True
    CHAINLINK_AGGREGATOR_BTC = chainlink_aggregator_btc
    CHAINLINK_PRICE_PRECISION_BTC = 10**convert(chainlink_aggregator_btc.decimals(), uint256)
    BOUND_SIZE = bound_size


@internal
@view
def _raw_price(agg_price: uint256) -> uint256:
    p_crypto_stable: uint256 = TRICRYPTO.price_oracle(TRICRYPTO_IX)          # d_crvusd/d_tbtc
    p_stable_agg: uint256 = agg_price                                        # d_usd/d_crvusd
    price: uint256 = p_crypto_stable * p_stable_agg / 10**18    # d_usd/d_tbtc

    # Limit BTC price
    if self.use_chainlink:
        chainlink_lrd: ChainlinkAnswer = CHAINLINK_AGGREGATOR_BTC.latestRoundData()
        if block.timestamp - min(chainlink_lrd.updated_at, block.timestamp) <= CHAINLINK_STALE_THRESHOLD:
            chainlink_p: uint256 = convert(chainlink_lrd.answer, uint256) * 10**18 / CHAINLINK_PRICE_PRECISION_BTC
            lower: uint256 = chainlink_p * (10**18 - BOUND_SIZE) / 10**18
            upper: uint256 = chainlink_p * (10**18 + BOUND_SIZE) / 10**18
            price = min(max(price, lower), upper)

    return price


@external
@view
def raw_price() -> uint256:
    return self._raw_price(STABLESWAP_AGGREGATOR.price())


@external
@view
def price() -> uint256:
    return self._raw_price(STABLESWAP_AGGREGATOR.price())


@external
def price_w() -> uint256:
    return self._raw_price(STABLESWAP_AGGREGATOR.price_w())


@external
def set_use_chainlink(do_it: bool):
    assert msg.sender == FACTORY.admin()
    self.use_chainlink = do_it
