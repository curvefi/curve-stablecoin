"""
Converts Chainlink answer from latestRoundData to 1e18-based rate for LRTs
"""

interface ChainlinkOracle:
    def latestRoundData() -> ChainlinkAnswer: view
    def decimals() -> uint256: view  # In reality uint8

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
    DECIMAL_MUL = 10**(18 - feed.decimals())
    FEED = feed


@external
@view
def rate() -> uint256:
    return convert(FEED.latestRoundData().answer, uint256) * DECIMAL_MUL
