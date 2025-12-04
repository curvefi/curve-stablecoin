# @version 0.3.10

"""
This contract is for testing only.
If you see it on mainnet - it won't be used for anything except testing the actual deployment
"""

from vyper.interfaces import ERC20

@external
def exchange(in_coin: address, out_coin: address, in_amount: uint256, out_amount: uint256):
    assert ERC20(in_coin).transferFrom(msg.sender, self, in_amount, default_return_value=True)
    assert ERC20(out_coin).transfer(msg.sender, out_amount, default_return_value=True)
