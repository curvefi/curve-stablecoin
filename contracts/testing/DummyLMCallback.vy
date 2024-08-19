# @version 0.3.10

MAX_TICKS_UINT: constant(uint256) = 50

_debug_collateral_per_share: public(HashMap[int256, uint256])
_debug_user_shares: public(HashMap[address, HashMap[int256, uint256]])

AMM: immutable(address)


@external
def __init__(amm: address):
    AMM = amm


@external
def callback_collateral_shares(n: int256, collateral_per_share: DynArray[uint256, MAX_TICKS_UINT]):
    assert msg.sender == AMM
    i: int256 = n
    for s in collateral_per_share:
        self._debug_collateral_per_share[i] = s
        i += 1


@external
def callback_user_shares(user: address, n: int256, user_shares: DynArray[uint256, MAX_TICKS_UINT]):
    assert msg.sender == AMM
    i: int256 = n
    for s in user_shares:
        self._debug_user_shares[user][i] = s
        i += 1
