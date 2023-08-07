# @version ^0.3.9
"""
@notice Chainlink Aggregator Mock for testing
"""

decimals: public(uint8)
ADMIN: immutable(address)
price: int256


@payable
@external
def __init__(decimals: uint8, admin: address, price: int256):
    self.decimals = decimals

    ADMIN = admin
    self.price = price


@external
@view
def latestRoundData() -> (uint80, int256, uint256, uint256, uint80):
    """
    returns (roundId, answer, startedAt, updatedAt, answeredInRound)
    """

    round_id: uint80 = convert(block.number, uint80)
    return round_id, self.price * 10**convert(self.decimals, int256), block.timestamp, block.timestamp, round_id


@external
def set_price(price: int256):
    assert msg.sender == ADMIN
    self.price = price
