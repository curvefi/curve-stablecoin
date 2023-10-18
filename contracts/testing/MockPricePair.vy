# @version 0.3.9

"""
This contract is for testing only.
If you see it on mainnet - it won't be used for anything except testing the actual deployment
"""

price: public(uint256)
coins: public(address[2])


@external
def __init__(price: uint256, stablecoin: address):
    self.price = price
    self.coins = [empty(address), stablecoin]


@external
@view
def price_oracle() -> uint256:
    return self.price


@external
@view
def get_p() -> uint256:
    return self.price


@external
def set_price(price: uint256):
    self.price = price

@external
@view
def get_virtual_price() -> uint256:
    return 10 ** 18  # 1.0


@external
@view
def totalSupply() -> uint256:
    return 10 ** 9 * 10 ** 18  # 1B
