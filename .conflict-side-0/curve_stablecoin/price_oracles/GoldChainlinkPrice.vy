# @version 0.3.10
"""
@title GoldChainlinkPrice
@notice Price oracle for gold (initially) which JUST uses chainlink. Generally better to do EMA instead
@author Curve.Fi
@license MIT
"""

struct ChainlinkAnswer:
    round_id: uint80
    answer: int256
    started_at: uint256
    updated_at: uint256
    answered_in_round: uint80

interface ChainlinkAggregator:
    def latestRoundData() -> ChainlinkAnswer: view
    def decimals() -> uint8: view


CHAINLINK_AGGREGATOR: immutable(ChainlinkAggregator)
CHAINLINK_PRICE_PRECISION: immutable(uint256)


@external
def __init__(
        chainlink_aggregator: ChainlinkAggregator
    ):
    CHAINLINK_AGGREGATOR = chainlink_aggregator
    CHAINLINK_PRICE_PRECISION = 10**convert(18 - chainlink_aggregator.decimals(), uint256)


@internal
@view
def _price() -> uint256:
    price: uint256 = convert(CHAINLINK_AGGREGATOR.latestRoundData().answer, uint256) * CHAINLINK_PRICE_PRECISION
    assert price > 0, "Chainlink fail"
    return price


@external
@view
def price() -> uint256:
    return self._price()


@external
def price_w() -> uint256:
    return self._price()
