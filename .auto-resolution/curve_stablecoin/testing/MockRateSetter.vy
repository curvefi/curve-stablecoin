# @version 0.3.10

rate: public(uint256)


@external
def __init__(rate: uint256):
    self.rate = rate


@external
def set_rate(rate: uint256):
    self.rate = rate
