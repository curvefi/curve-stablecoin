# pragma version 0.4.3
# SPDX-License-Identifier: MIT
"""
@title Chainlink Price Oracle
@license MIT
@notice Adapts a Chainlink price feed to a WAD price; unusable data reverts.
@dev Assumes feed decimals remain unchanged, as in GoldChainlinkPrice.
@custom:kill There is no need to kill this contract, just kill the underlying market
"""

from curve_stablecoin.interfaces import IPriceOracle

implements: IPriceOracle


struct ChainlinkAnswer:
    round_id: uint80
    answer: int256
    started_at: uint256
    updated_at: uint256
    answered_in_round: uint80


interface Feed:
    def decimals() -> uint8: view
    def latestRoundData() -> ChainlinkAnswer: view


FEED: public(immutable(Feed))
MAX_AGE: public(immutable(uint256))
DECIMAL_MUL: immutable(uint256)


@deploy
def __init__(feed: Feed, max_age: uint256):
    assert feed.address != empty(address) and max_age > 0
    FEED = feed
    MAX_AGE = max_age
    DECIMAL_MUL = 10**(18 - convert(staticcall feed.decimals(), uint256))


@internal
@view
def _price() -> uint256:
    data: ChainlinkAnswer = staticcall FEED.latestRoundData()
    assert data.answer > 0, "Invalid answer"
    assert data.updated_at > 0 and block.timestamp - data.updated_at <= MAX_AGE, "Stale price"
    return convert(data.answer, uint256) * DECIMAL_MUL


@external
@view
def price() -> uint256:
    return self._price()


@external
def price_w() -> uint256:
    return self._price()
