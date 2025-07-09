# @version 0.4.1

"""
This contract is for testing only.
If you see it on mainnet - it won't be used for anything except testing the actual deployment
"""

MAX_COINS: constant(uint256) = 8

ADMIN: immutable(address)
coins: public(immutable(DynArray[address, MAX_COINS]))
prices: DynArray[uint256, MAX_COINS - 1]


@deploy
def __init__(_admin: address, _prices: DynArray[uint256, MAX_COINS - 1]):
    ADMIN = _admin
    self.prices = _prices
    _coins: DynArray[address, MAX_COINS] = []
    for i: uint256 in range(len(_prices) + 1, bound=MAX_COINS):
        _coins.append(empty(address))

    coins = _coins


@external
@view
def price_oracle(_i: uint256) -> uint256:
    return self.prices[_i]


@external
def set_price(_i: uint256, _price: uint256):
    assert msg.sender == ADMIN
    self.prices[_i] = _price
