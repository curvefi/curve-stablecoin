# @version 0.3.1

interface ERC20:
    def mint(_to: address, _value: uint256) -> bool: nonpayable
    def burnFrom(_to: address, _value: uint256) -> bool: nonpayable
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable


STABLECOIN: immutable(address)
controllers: HashMap[address, address]
amms: HashMap[address, address]
admin: public(address)
controller_implementation: public(address)


@external
def __init__(stablecoin: address,
             controller_implementation: address,
             admin: address):
    STABLECOIN = stablecoin
    self.admin = admin
    self.controller_implementation = controller_implementation


@external
def create_market(token: uint256) -> address[2]:
    return [ZERO_ADDRESS, ZERO_ADDRESS]


@external
def set_admin(admin: address):
    assert msg.sender == self.admin
    self.admin = admin
