# pragma version 0.4.3

"""
@title MockControllerMP
@notice Minimal controller stand-in for HyperbolicDynamicMP unit tests.
        Exposes the settable accounting values the policy reads
        (`total_debt`, `available_balance`, `admin_fees`) and returns a
        configurable `factory` address (whose `admin()` the policy resolves
        for access control).
"""

total_debt: public(uint256)
available_balance: public(uint256)
admin_fees: public(uint256)
factory: public(address)


@deploy
def __init__(_factory: address):
    self.factory = _factory


@external
def set_state(_total_debt: uint256, _available_balance: uint256, _admin_fees: uint256):
    self.total_debt = _total_debt
    self.available_balance = _available_balance
    self.admin_fees = _admin_fees
