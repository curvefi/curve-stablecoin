# @version 0.3.10

"""
This contract is for testing only.
If you see it on mainnet - it won't be used for anything except testing the actual deployment
"""

interface ERC20:
    def transfer(_to: address, _value: uint256) -> bool: nonpayable
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable
    def balanceOf(_for: address) -> uint256: view


@external
def exchange(_x: address, _y: address, _in_amount: uint256, _out_amount: uint256):
    assert ERC20(_x).transferFrom(msg.sender, self, _in_amount, default_return_value=True)
    assert ERC20(_y).transfer(msg.sender, _out_amount, default_return_value=True)
