# @version 0.3.7
"""
@title veBoost Mock
"""
from vyper.interfaces import ERC20

VOTING_ESCROW: immutable(address)


@external
def __init__(_voting_escrow: address):
    VOTING_ESCROW = _voting_escrow


@view
@external
def adjusted_balance_of(_user: address) -> uint256:
    return ERC20(VOTING_ESCROW).balanceOf(_user)
