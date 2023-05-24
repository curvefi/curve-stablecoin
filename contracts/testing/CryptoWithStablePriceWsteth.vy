# @version 0.3.7
"""
@title CryptoWithStablePriceWsteth
@notice Price oracle for tricrypto+wsteth for crvUSD. Not limiting the price with chainlink - relying on tricrypto-ng
@notice With old tricrypto2 it is UNSAFE to use. Should be tricrypto-ng + steth-ng
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


TRICRYPTO: immutable(Tricrypto)
TRICRYPTO_IX: immutable(uint256)
STABLESWAP_AGGREGATOR: immutable(StableAggregator)
STABLESWAP: immutable(Stableswap)
STABLECOIN: immutable(address)
REDEEMABLE: immutable(address)
IS_INVERSE: immutable(bool)

STAKEDSWAP: immutable(Stableswap)
WSTETH: immutable(wstETH)


@external
def __init__(
        tricrypto: Tricrypto, ix: uint256, stableswap: Stableswap, staked_swap: Stableswap, stable_aggregator: StableAggregator,
        wsteth: wstETH
    ):
    TRICRYPTO = tricrypto
    TRICRYPTO_IX = ix
    STABLESWAP_AGGREGATOR = stable_aggregator
    STABLESWAP = stableswap
    STAKEDSWAP = staked_swap
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
    price_per_share: uint256 = WSTETH.stEthPerToken()
    p_staked: uint256 = min(STAKEDSWAP.price_oracle(), 10**18) * price_per_share / 10**18  # d_eth / d_steth

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
