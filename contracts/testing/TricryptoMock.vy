# @version 0.3.10

coins: public(address[3])
price_oracle: public(uint256[3])

@external
def __init__(coins: address[3]):
    self.coins = coins


@external
def set_price(i: uint256, price: uint256):
    self.price_oracle[i] = price
