# @version 0.3.1

admin: public(address)
rate: public(int256)


@external
def __init__(admin: address):
    self.admin = admin


@external
def set_admin(admin: address):
    assert msg.sender == self.admin
    self.admin = admin


@external
def rate_write() -> int256:
    return self.rate


@external
def set_rate(rate: int256):
    assert msg.sender == self.admin
    self.rate = rate
