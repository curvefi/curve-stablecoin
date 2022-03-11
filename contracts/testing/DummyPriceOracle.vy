# @version 0.3.1
price: public(uint256)
ADMIN: immutable(address)


@external
def __init__(admin: address, price: uint256):
    self.price = price
    ADMIN = admin


@external
def set_price(price: uint256):
    assert msg.sender == ADMIN
    self.price = price
