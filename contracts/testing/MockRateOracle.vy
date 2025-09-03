# pragma version 0.4.3
"""
@title MockRateOracle
@notice Mock to tweak rate
"""

rates: public(uint256[2])


@deploy
def __init__():
    self.rates = [10 ** 18, 10 ** 18]


@view
@external
def get00() -> uint256:
    return self.rates[0]


@view
@external
def get11() -> uint256:
    return self.rates[1]


@external
def set(i: uint256, rate: uint256):
    self.rates[i] = rate
