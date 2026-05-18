# pragma version 0.4.3

from curve_std.interfaces import IERC20
from curve_stablecoin.interfaces import IController


_rate: uint256

@deploy
def __init__(borrowed_token: IERC20, min_rate: uint256, max_rate: uint256):
    # Testing policy: no admin mechanics; initialize to provided min_rate
    self._rate = min_rate


@external
def set_rate(rate: uint256):
    # Testing policy: callable by anyone in tests
    self._rate = rate


@external
def rate_write(_for: address = msg.sender) -> uint256:
    _: uint256 = staticcall IController(_for).available_balance()
    _ = staticcall IController(_for).total_debt()
    _ = staticcall IController(_for).admin_fees()
    return self._rate


@external
@view
def rate(_for: address = msg.sender) -> uint256:
    _: uint256 = staticcall IController(_for).available_balance()
    _ = staticcall IController(_for).total_debt()
    _ = staticcall IController(_for).admin_fees()
    return self._rate
