# pragma version 0.4.3

"""
@title MockRateCalculator
@notice Minimal stand-in for the external rate calculator used by
        HyperbolicDynamicMP. Returns a settable per-second rate and can be
        toggled to revert, to exercise the fallback-to-0 path in `rate_write`.
"""

rate_value: public(uint256)
should_revert: public(bool)


@deploy
def __init__(_rate: uint256):
    self.rate_value = _rate


@external
@view
def rate() -> uint256:
    assert not self.should_revert, "rate calc reverted"
    return self.rate_value


@external
def set_rate(_rate: uint256):
    self.rate_value = _rate


@external
def set_should_revert(_should_revert: bool):
    self.should_revert = _should_revert
