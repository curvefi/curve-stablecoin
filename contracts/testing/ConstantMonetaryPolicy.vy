# @version 0.4.3
"""
Although this monetary policy works, it's only intended to be used in tests
"""

admin: public(address)
rate: public(uint256)


@deploy
def __init__(admin: address):
    self.admin = admin


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
