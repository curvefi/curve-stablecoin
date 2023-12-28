# @version 0.3.10

"""
This contract is for testing only.
If you see it on mainnet - it won't be used for anything except testing the actual deployment
"""

price: public(uint256)
ADMIN: immutable(address)


@external
def __init__(admin: address, price: uint256):
    self.price = price
    ADMIN = admin


@external
def price_w() -> uint256:
    # State-changing price oracle in case we want to include EMA
    return self.price


@external
def set_price(price: uint256):
    assert msg.sender == ADMIN
    self.price = price
