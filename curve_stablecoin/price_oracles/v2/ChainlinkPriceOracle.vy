# pragma version 0.4.3
# SPDX-License-Identifier: MIT
"""
@title Chainlink Price Oracle
@license MIT
@notice Adapts a Chainlink price feed to a WAD price; unusable data reverts.
@custom:kill There is no need to kill this contract, just kill the underlying market
"""

from curve_stablecoin.interfaces import IPriceOracle

implements: IPriceOracle


interface Feed:
    def decimals() -> uint8: view
    def latestRoundData() -> (uint80, int256, uint256, uint256, uint80): view


FEED: public(immutable(Feed))
MAX_AGE: public(immutable(uint256))


@deploy
def __init__(feed: Feed, max_age: uint256):
    assert feed.address != empty(address) and max_age > 0
    FEED = feed
    MAX_AGE = max_age
    assert self._price() > 0


@internal
@view
def _price() -> uint256:
    data: (uint80, int256, uint256, uint256, uint80) = staticcall FEED.latestRoundData()
    assert data[1] > 0, "Invalid answer"
    assert data[3] > 0 and data[3] <= block.timestamp, "Invalid timestamp"
    assert block.timestamp - data[3] <= MAX_AGE, "Stale price"
    # Read decimals again so a feed upgrade cannot silently change the scale.
    decimals: uint256 = convert(staticcall FEED.decimals(), uint256)
    assert decimals <= 18, "Invalid decimals"
    return convert(data[1], uint256) * 10**(18 - decimals)


@external
@view
def price() -> uint256:
    return self._price()


@external
def price_w() -> uint256:
    return self._price()
