"""
Converts Chainlink answer from latestRoundData to 1e18-based rate for LRTs
"""

interface ChainlinkOracle:
    def latestRoundData() -> ChainlinkAnswer: view
    def decimals() -> uint8: view

struct ChainlinkAnswer:
    roundID: uint80
    answer: int256
    startedAt: uint256
    updatedAt: uint256
    answeredInRound: uint80


DECIMAL_MUL: immutable(uint256)
FEED: public(immutable(ChainlinkOracle))


@external
def __init__(feed: ChainlinkOracle):
    FEED = feed
    DECIMAL_MUL = 10**(18 - convert(feed.decimals(), uint256))


@external
@view
def rate() -> uint256:
    return convert(FEED.latestRoundData().answer, uint256) * DECIMAL_MUL
