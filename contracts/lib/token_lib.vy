# TODO missing pragmas
from contracts.interfaces import IERC20


@internal
def max_approve(token: IERC20, spender: address):
    if staticcall token.allowance(self, spender) == 0:
        assert extcall token.approve(spender, max_value(uint256), default_return_value=True)


@internal
def transfer_from(token: IERC20, _from: address, _to: address, amount: uint256):
    if amount > 0:
        assert extcall token.transferFrom(_from, _to, amount, default_return_value=True)


@internal
def transfer(token: IERC20, _to: address, amount: uint256):
    if amount > 0:
        assert extcall token.transfer(_to, amount, default_return_value=True)
