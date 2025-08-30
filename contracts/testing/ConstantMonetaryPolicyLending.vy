# @version 0.4.3
"""
Although this monetary policy works, it's only intended to be used in tests
"""

from ethereum.ercs import IERC20


admin: public(address)
rate: public(uint256)


@deploy
def __init__(borrowed_token: IERC20, min_rate: uint256, max_rate: uint256):
    self.admin = tx.origin
    self.rate = min_rate


@external
def set_admin(admin: address):
    assert msg.sender == self.admin
    self.admin = admin


@external
def rate_write() -> uint256:
    return self.rate


@external
def set_rate(rate: uint256):
    assert msg.sender == self.admin
    self.rate = rate
