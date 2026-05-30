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
def rate_write() -> uint256:
    controller: IController = IController(msg.sender)
    _: uint256 = staticcall controller.available_balance()
    _ = staticcall controller.total_debt()
    _ = staticcall controller.admin_fees()
    return self._rate


@external
@view
def rate() -> uint256:
    controller: IController = IController(msg.sender)
    _: uint256 = staticcall controller.available_balance()
    _ = staticcall controller.total_debt()
    _ = staticcall controller.admin_fees()
    return self._rate
