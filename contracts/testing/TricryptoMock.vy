# pragma version 0.4.3

coins: public(address[3])
price_oracle: public(uint256[3])

@deploy
def __init__(coins: address[3]):
    self.coins = coins


@external
def set_price(i: uint256, price: uint256):
    self.price_oracle[i] = price
