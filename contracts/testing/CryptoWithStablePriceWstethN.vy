# @version 0.3.7
"""
@title CryptoWithStablePriceWsteth
@notice Price oracle for tricrypto+wsteth for crvUSD. Not limiting the price with chainlink - relying on tricrypto-ng
        With old tricrypto2 it is UNSAFE to use. Should be tricrypto-ng + steth-ng
@author Curve.Fi
@license MIT
"""

# Tricrypto-ng
interface Tricrypto:
    def price_oracle(k: uint256) -> uint256: view
    def coins(i: uint256) -> address: view
    def totalSupply() -> uint256: view

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
CHAINLINK_AGGREGATOR_STETH: immutable(ChainlinkAggregator)
CHAINLINK_PRICE_PRECISION_STETH: immutable(uint256)
CHAINLINK_STALE_THRESHOLD: constant(uint256) = 86400
BOUND_SIZE: public(immutable(uint256))

STAKEDSWAP: public(immutable(Stableswap))
WSTETH: public(immutable(wstETH))

use_chainlink: public(bool)


@external
def __init__(
        tricrypto: Tricrypto[N_POOLS],
        ix: uint256[N_POOLS],
        stableswap: Stableswap[N_POOLS],
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
    IS_INVERSE = _is_inverse
    REDEEMABLE = _redeemable

    self.use_chainlink = True
    CHAINLINK_AGGREGATOR_ETH = chainlink_aggregator_eth
    CHAINLINK_PRICE_PRECISION_ETH = 10**convert(chainlink_aggregator_eth.decimals(), uint256)
    CHAINLINK_AGGREGATOR_STETH = chainlink_aggregator_steth
    CHAINLINK_PRICE_PRECISION_STETH = 10**convert(chainlink_aggregator_steth.decimals(), uint256)
    BOUND_SIZE = bound_size


@internal
@view
def _raw_price() -> uint256:
    weighted_price: uint256 = 0
    weights: uint256 = 0
    for i in range(N_POOLS):
        p_crypto_r: uint256 = TRICRYPTO[i].price_oracle(TRICRYPTO_IX[i])  # d_usdt/d_eth
        p_stable_r: uint256 = STABLESWAP[i].price_oracle()             # d_usdt/d_st
        p_stable_agg: uint256 = STABLESWAP_AGGREGATOR.price()       # d_usd/d_st
        if IS_INVERSE[i]:
            p_stable_r = 10**36 / p_stable_r
        weight: uint256 = TRICRYPTO[i].totalSupply()
        weights += weight
        weighted_price += p_crypto_r * p_stable_agg / p_stable_r * weight     # d_usd/d_eth
    crv_p: uint256 = weighted_price / weights

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
