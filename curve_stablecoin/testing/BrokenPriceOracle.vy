# pragma version 0.4.3

"""
This contract is for testing only.
Simulates a broken oracle whose price() always reverts.
"""


@external
def price_w() -> uint256:
    raise "broken"


@external
@view
def price() -> uint256:
    raise "broken"
