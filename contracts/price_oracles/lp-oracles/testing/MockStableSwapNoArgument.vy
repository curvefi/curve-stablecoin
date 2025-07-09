# @version 0.4.1

"""
This contract is for testing only.
If you see it on mainnet - it won't be used for anything except testing the actual deployment
"""

MAX_COINS: constant(uint256) = 2

ADMIN: immutable(address)
coins: public(immutable(address[2]))
price_oracle: uint256


@deploy
def __init__(_admin: address, _price: uint256):
    ADMIN = _admin
    self.price_oracle = _price
    coins = [empty(address), empty(address)]


@external
def set_price(_price: uint256):
    assert msg.sender == ADMIN
    self.price_oracle = _price
