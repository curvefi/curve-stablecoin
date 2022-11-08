# @version 0.3.7
"""
@title Curve USD Stablecoin
@author CurveFi
"""
from vyper.interfaces import ERC20

implements: ERC20


event Approval:
    owner: indexed(address)
    spender: indexed(address)
    value: uint256

event Transfer:
    sender: indexed(address)
    receiver: indexed(address)
    value: uint256


decimals: public(constant(uint8)) = 18
version: public(constant(String[8])) = "1"

EIP712_TYPEHASH: constant(bytes32) = keccak256(
    "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract,bytes32 salt)"
)
VERSION_HASH: constant(bytes32) = keccak256(version)


name: public(immutable(String[64]))
symbol: public(immutable(String[32]))

NAME_HASH: immutable(bytes32)
CACHED_CHAIN_ID: immutable(uint256)
salt: public(immutable(bytes32))
CACHED_DOMAIN_SEPARATOR: immutable(bytes32)


allowance: public(HashMap[address, HashMap[address, uint256]])
balanceOf: public(HashMap[address, uint256])
totalSupply: public(uint256)


@external
def __init__(_name: String[64], _symbol: String[32]):
    name = _name
    symbol = _symbol

    NAME_HASH = keccak256(_name)
    CACHED_CHAIN_ID = chain.id
    salt = block.prevhash
    CACHED_DOMAIN_SEPARATOR = keccak256(
        _abi_encode(
            EIP712_TYPEHASH,
            keccak256(_name),
            NAME_HASH,
            chain.id,
            self,
            block.prevhash,
        )
    )


@internal
def _approve(_owner: address, _spender: address, _value: uint256):
    self.allowance[_owner][_spender] = _value

    log Approval(_owner, _spender, _value)


@internal
def _burn(_from: address, _value: uint256):
    self.balanceOf[_from] -= _value
    self.totalSupply -= _value

    log Transfer(_from, empty(address), _value)


@internal
def _transfer(_from: address, _to: address, _value: uint256):
    assert _to not in [self, empty(address)]

    self.balanceOf[_from] -= _value
    self.balanceOf[_to] += _value

    log Transfer(_from, _to, _value)


@view
@internal
def _domain_separator() -> bytes32:
    if chain.id != CACHED_CHAIN_ID:
        return keccak256(
            _abi_encode(
                EIP712_TYPEHASH,
                NAME_HASH,
                VERSION_HASH,
                chain.id,
                self,
                salt,
            )
        )
    return CACHED_DOMAIN_SEPARATOR


@external
def transferFrom(_from: address, _to: address, _value: uint256) -> bool:
    allowance: uint256 = self.allowance[_from][msg.sender]
    if allowance != max_value(uint256):
        self._approve(_from, msg.sender, allowance - _value)

    self._transfer(_from, _to, _value)
    return True


@external
def transfer(_to: address, _value: uint256) -> bool:
    self._transfer(msg.sender, _to, _value)
    return True


@external
def approve(_spender: address, _value: uint256) -> bool:
    self._approve(msg.sender, _spender, _value)
    return True


@external
def increaseAllowance(_spender: address, _add_value: uint256) -> bool:
    cached_allowance: uint256 = self.allowance[msg.sender][_spender]
    allowance: uint256 = unsafe_add(cached_allowance, _add_value)

    # check for an overflow
    if allowance < cached_allowance:
        allowance = max_value(uint256)
    
    if allowance != cached_allowance:
        self._approve(msg.sender, _spender, allowance)

    return True


@external
def decreaseAllowance(_spender: address, _sub_value: uint256) -> bool:
    cached_allowance: uint256 = self.allowance[msg.sender][_spender]
    allowance: uint256 = unsafe_sub(cached_allowance, _sub_value)

    # check for an underflow
    if cached_allowance < allowance:
        allowance = 0

    if allowance != cached_allowance:
        self._approve(msg.sender, _spender, allowance)

    return True


@external
def burnFrom(_from: address, _value: uint256) -> bool:
    allowance: uint256 = self.allowance[_from][msg.sender]
    if allowance != max_value(uint256):
        self._approve(_from, msg.sender, allowance - _value)

    self._burn(_from, _value)
    return True


@external
def burn(_value: uint256) -> bool:
    self._burn(msg.sender, _value)
    return True
