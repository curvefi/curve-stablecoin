# @version 0.4.1

"""
This contract is for testing only.
If you see it on mainnet - it won't be used for anything except testing the actual deployment
"""

lp_price: public(uint256)
ADMIN: immutable(address)


@deploy
def __init__(_admin: address, _lp_price: uint256):
    self.lp_price = _lp_price
    ADMIN = _admin


@external
def set_lp_price(_lp_price: uint256):
    assert msg.sender == ADMIN
    self.lp_price = _lp_price
