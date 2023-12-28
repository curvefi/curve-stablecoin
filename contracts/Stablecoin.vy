# @version 0.3.10
"""
@title crvUSD Stablecoin
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2023 - all rights reserved
"""
from vyper.interfaces import ERC20

implements: ERC20


interface ERC1271:
    def isValidSignature(_hash: bytes32, _signature: Bytes[65]) -> bytes4: view


event Approval:
    owner: indexed(address)
    spender: indexed(address)
    value: uint256

event Transfer:
    sender: indexed(address)
    receiver: indexed(address)
    value: uint256

event SetMinter:
    minter: indexed(address)


decimals: public(constant(uint8)) = 18
version: public(constant(String[8])) = "v1.0.0"

ERC1271_MAGIC_VAL: constant(bytes4) = 0x1626ba7e
EIP712_TYPEHASH: constant(bytes32) = keccak256(
    "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract,bytes32 salt)"
)
EIP2612_TYPEHASH: constant(bytes32) = keccak256(
    "Permit(address owner,address spender,uint256 value,uint256 nonce,uint256 deadline)"
)
VERSION_HASH: constant(bytes32) = keccak256(version)


name: public(immutable(String[64]))
symbol: public(immutable(String[32]))
salt: public(immutable(bytes32))

NAME_HASH: immutable(bytes32)
CACHED_CHAIN_ID: immutable(uint256)
CACHED_DOMAIN_SEPARATOR: immutable(bytes32)


allowance: public(HashMap[address, HashMap[address, uint256]])
balanceOf: public(HashMap[address, uint256])
totalSupply: public(uint256)

nonces: public(HashMap[address, uint256])
minter: public(address)


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
            VERSION_HASH,
            chain.id,
            self,
            block.prevhash,
        )
    )

    self.minter = msg.sender
    log SetMinter(msg.sender)


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
    """
    @notice Transfer tokens from one account to another.
    @dev The caller needs to have an allowance from account `_from` greater than or
        equal to the value being transferred. An allowance equal to the uint256 type's
        maximum, is considered infinite and does not decrease.
    @param _from The account which tokens will be spent from.
    @param _to The account which tokens will be sent to.
    @param _value The amount of tokens to be transferred.
    """
    allowance: uint256 = self.allowance[_from][msg.sender]
    if allowance != max_value(uint256):
        self._approve(_from, msg.sender, allowance - _value)

    self._transfer(_from, _to, _value)
    return True


@external
def transfer(_to: address, _value: uint256) -> bool:
    """
    @notice Transfer tokens to `_to`.
    @param _to The account to transfer tokens to.
    @param _value The amount of tokens to transfer.
    """
    self._transfer(msg.sender, _to, _value)
    return True


@external
def approve(_spender: address, _value: uint256) -> bool:
    """
    @notice Allow `_spender` to transfer up to `_value` amount of tokens from the caller's account.
    @dev Non-zero to non-zero approvals are allowed, but should be used cautiously. The methods
        increaseAllowance + decreaseAllowance are available to prevent any front-running that
        may occur.
    @param _spender The account permitted to spend up to `_value` amount of caller's funds.
    @param _value The amount of tokens `_spender` is allowed to spend.
    """
    self._approve(msg.sender, _spender, _value)
    return True


@external
def permit(
    _owner: address,
    _spender: address,
    _value: uint256,
    _deadline: uint256,
    _v: uint8,
    _r: bytes32,
    _s: bytes32,
) -> bool:
    """
    @notice Permit `_spender` to spend up to `_value` amount of `_owner`'s tokens via a signature.
    @dev In the event of a chain fork, replay attacks are prevented as domain separator is recalculated.
        However, this is only if the resulting chains update their chainId.
    @param _owner The account which generated the signature and is granting an allowance.
    @param _spender The account which will be granted an allowance.
    @param _value The approval amount.
    @param _deadline The deadline by which the signature must be submitted.
    @param _v The last byte of the ECDSA signature.
    @param _r The first 32 bytes of the ECDSA signature.
    @param _s The second 32 bytes of the ECDSA signature.
    """
    assert _owner != empty(address) and block.timestamp <= _deadline

    nonce: uint256 = self.nonces[_owner]
    digest: bytes32 = keccak256(
        concat(
            b"\x19\x01",
            self._domain_separator(),
            keccak256(_abi_encode(EIP2612_TYPEHASH, _owner, _spender, _value, nonce, _deadline)),
        )
    )

    if _owner.is_contract:
        sig: Bytes[65] = concat(_abi_encode(_r, _s), slice(convert(_v, bytes32), 31, 1))
        assert ERC1271(_owner).isValidSignature(digest, sig) == ERC1271_MAGIC_VAL
    else:
        assert ecrecover(digest, _v, _r, _s) == _owner

    self.nonces[_owner] = nonce + 1
    self._approve(_owner, _spender, _value)
    return True


@external
def increaseAllowance(_spender: address, _add_value: uint256) -> bool:
    """
    @notice Increase the allowance granted to `_spender`.
    @dev This function will never overflow, and instead will bound
        allowance to MAX_UINT256. This has the potential to grant an
        infinite approval.
    @param _spender The account to increase the allowance of.
    @param _add_value The amount to increase the allowance by.
    """
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
    """
    @notice Decrease the allowance granted to `_spender`.
    @dev This function will never underflow, and instead will bound
        allowance to 0.
    @param _spender The account to decrease the allowance of.
    @param _sub_value The amount to decrease the allowance by.
    """
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
    """
    @notice Burn `_value` amount of tokens from `_from`.
    @dev The caller must have previously been given an allowance by `_from`.
    @param _from The account to burn the tokens from.
    @param _value The amount of tokens to burn.
    """
    allowance: uint256 = self.allowance[_from][msg.sender]
    if allowance != max_value(uint256):
        self._approve(_from, msg.sender, allowance - _value)

    self._burn(_from, _value)
    return True


@external
def burn(_value: uint256) -> bool:
    """
    @notice Burn `_value` amount of tokens.
    @param _value The amount of tokens to burn.
    """
    self._burn(msg.sender, _value)
    return True


@external
def mint(_to: address, _value: uint256) -> bool:
    """
    @notice Mint `_value` amount of tokens to `_to`.
    @dev Only callable by an account with minter privileges.
    @param _to The account newly minted tokens are credited to.
    @param _value The amount of tokens to mint.
    """
    assert msg.sender == self.minter
    assert _to not in [self, empty(address)]

    self.balanceOf[_to] += _value
    self.totalSupply += _value

    log Transfer(empty(address), _to, _value)
    return True


@external
def set_minter(_minter: address):
    assert msg.sender == self.minter

    self.minter = _minter
    log SetMinter(_minter)


@view
@external
def DOMAIN_SEPARATOR() -> bytes32:
    """
    @notice EIP712 domain separator.
    """
    return self._domain_separator()
