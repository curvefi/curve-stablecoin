# pragma version 0.4.3

from ethereum.ercs import IERC20
implements: IERC20

from snekmate.tokens import erc20
from snekmate.auth import ownable

initializes: ownable
initializes: erc20[ownable := ownable]

exports: erc20.__interface__


@deploy
def __init__(decimals: uint256):
    ownable.__init__()
    erc20.__init__("mock", "mock", convert(decimals, uint8), "mock", "mock")


@external
def _mint_for_testing(_target: address, _value: uint256) -> bool:
    erc20._mint(_target, _value)
    log IERC20.Transfer(sender=empty(address), receiver=_target, value=_value)
    return True
