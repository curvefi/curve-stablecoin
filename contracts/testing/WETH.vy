# @version ^0.3.9
"""
@notice Mock ERC20 for testing
"""

event Transfer:
    _from: indexed(address)
    _to: indexed(address)
    _value: uint256

event Approval:
    _owner: indexed(address)
    _spender: indexed(address)
    _value: uint256

name: public(String[64])
symbol: public(String[32])
decimals: public(uint256)
balanceOf: public(HashMap[address, uint256])
allowances: HashMap[address, HashMap[address, uint256]]
total_supply: uint256


@payable
@external
def __init__():
    self.name = "Wrapped Ether"
    self.symbol = "WETH"
    self.decimals = 18


@external
@view
def totalSupply() -> uint256:
    return self.total_supply


@external
@view
def allowance(_owner : address, _spender : address) -> uint256:
    return self.allowances[_owner][_spender]


@external
def transfer(_to : address, _value : uint256) -> bool:
    self.balanceOf[msg.sender] -= _value
    self.balanceOf[_to] += _value
    log Transfer(msg.sender, _to, _value)
    return True


@external
def transferFrom(_from : address, _to : address, _value : uint256) -> bool:
    self.balanceOf[_from] -= _value
    self.balanceOf[_to] += _value
    self.allowances[_from][msg.sender] -= _value
    log Transfer(_from, _to, _value)
    return True


@external
def approve(_spender : address, _value : uint256) -> bool:
    self.allowances[msg.sender][_spender] = _value
    log Approval(msg.sender, _spender, _value)
    return True


@external
def _mint_for_testing(_target: address, _value: uint256) -> bool:
    self.total_supply += _value
    self.balanceOf[_target] += _value
    log Transfer(empty(address), _target, _value)

    return True


@payable
@external
def deposit():
    self.balanceOf[msg.sender] += msg.value


@payable
@external
def __default__():
    self.balanceOf[msg.sender] += msg.value


@external
def withdraw(_amount: uint256):
    self.balanceOf[msg.sender] -= _amount
    raw_call(msg.sender, b"", value=_amount)
