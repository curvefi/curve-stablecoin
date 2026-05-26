# @version 0.4.3
"""
Although this monetary policy works, it's only intended to be used in tests
"""

admin: public(address)
_rate: uint256


@deploy
def __init__(admin: address):
    self.admin = admin


@external
def set_admin(admin: address):
    assert msg.sender == self.admin
    self.admin = admin


@external
@view
def rate(_for: address = msg.sender) -> uint256:
    return self._rate


@external
def rate_write(_for: address = msg.sender) -> uint256:
    return self._rate


@external
def set_rate(_rate: uint256):
    assert msg.sender == self.admin
    self._rate = _rate
