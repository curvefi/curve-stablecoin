# @version 0.3.10

"""
This contract is for testing only.
If you see it on mainnet - it won't be used for anything except testing the actual deployment
"""

pool: public(immutable(address))
IS_INVERSE: public(bool)
debt: public(uint256)

coins: public(address[2])
get_virtual_price: public(uint256)
totalSupply: public(uint256)

price: public(uint256)


@external
def __init__(price: uint256, stablecoin: address):
    pool = self
    self.IS_INVERSE = False
    self.debt = 0

    self.coins = [empty(address), stablecoin]
    self.get_virtual_price = 10 ** 18  # 1.0
    self.totalSupply = 10 ** 9 * 10 ** 18  # 1B

    self.price = price


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
def set_debt(debt: uint256):
    self.debt = debt
