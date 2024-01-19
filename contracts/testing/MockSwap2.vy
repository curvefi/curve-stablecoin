# @version 0.3.10

price_oracle: public(uint256)


@external
def __init__():
    self.price_oracle = 10**18


@external
def set_price(p: uint256):
    self.price_oracle = p
