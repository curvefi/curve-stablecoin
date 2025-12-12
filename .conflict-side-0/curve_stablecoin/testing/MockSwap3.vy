# @version 0.3.10

price_oracle: public(uint256[2])


@external
def __init__():
    self.price_oracle[0] = 10**18
    self.price_oracle[1] = 10**18


@external
def set_price(p: uint256, i: uint256 = 0):
    self.price_oracle[i] = p
