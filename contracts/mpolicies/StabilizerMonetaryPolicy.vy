# @version 0.3.1

interface Controller:
    def debt(user: address) -> uint256: view

admin: public(address)

rate0: public(int256)
halving_shift: public(uint256)  # 10**16

STABILIZER: immutable(address)
POOL: immutable(address)


@external
def __init__(admin: address, stabilizer: address, pool: address,
             halving_shift: uint256):
    self.admin = admin
    STABILIZER = stabilizer
    POOL = pool
    self.halving_shift = halving_shift


@external
def set_admin(admin: address):
    assert msg.sender == self.admin
    self.admin = admin


@internal
@view
def calculate_rate() -> uint256:
    return 0


@view
@external
def rate() -> uint256:
    return self.rate0


@external
def rate_write() -> int256:
    # do we need?
    return self.rate0


@external
def set_rate(rate: int256):
    assert msg.sender == self.admin
    self.rate0 = rate
