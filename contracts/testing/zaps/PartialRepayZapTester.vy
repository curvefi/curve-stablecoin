# pragma version 0.4.3

from curve_std.interfaces import IERC20
from curve_std import token as tkn


@external
def callback_liquidate_partial(calldata: Bytes[4 * 10**4 - 32 * 6 - 16]):
    borrowed: IERC20 = IERC20(convert(slice(calldata, 0, 20), address))
    tkn.max_approve(borrowed, msg.sender)
