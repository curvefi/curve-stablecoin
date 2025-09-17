# pragma version 0.4.3

from contracts.interfaces import IERC20

rate: public(uint256)

@deploy
def __init__(borrowed_token: IERC20, min_rate: uint256, max_rate: uint256):
    # Testing policy: no admin mechanics; initialize to provided min_rate
    self.rate = min_rate


@external
def rate_write() -> uint256:
    return self.rate


@external
def set_rate(rate: uint256):
    # Testing policy: callable by anyone in tests
    self.rate = rate
