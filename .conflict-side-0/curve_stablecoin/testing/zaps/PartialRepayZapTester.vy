# pragma version 0.4.3

from curve_std.interfaces import IERC20
from curve_std import token as tkn
from curve_stablecoin import constants as c


CALLDATA_MAX_SIZE: constant(uint256) = c.CALLDATA_MAX_SIZE


@external
def callback_liquidate_partial(calldata: Bytes[CALLDATA_MAX_SIZE - 32 * 6]):
    borrowed: IERC20 = IERC20(convert(slice(calldata, 0, 20), address))
    tkn.max_approve(borrowed, msg.sender)
