# @version 0.4.1

MAX_TICKS_UINT: constant(uint256) = 50

@external
def callback_collateral_shares(n_start: int256, collateral_per_share: DynArray[uint256, MAX_TICKS_UINT], size: uint256):
    raise "Error"


@external
def callback_user_shares(user: address, n_start: int256, old_user_shares: DynArray[uint256, MAX_TICKS_UINT], size: uint256):
    raise "Error"
