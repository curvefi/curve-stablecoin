# @version 0.3.1
"""
@title Wrapped token which represents a lent out asset
@author Curve.Fi
@dev Follows the ERC-20 token standard as defined at
     https://eips.ethereum.org/EIPS/eip-20
"""
interface ERC20:
    def decimals() -> uint256: view
    def name() -> String[64]: view
    def symbol() -> String[32]: view
    def transfer(_to: address, _value: uint256) -> bool: nonpayable
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable


event Transfer:
    _from: indexed(address)
    _to: indexed(address)
    _value: uint256

event Approval:
    _owner: indexed(address)
    _spender: indexed(address)
    _value: uint256


NAME: immutable(String[64])
SYMBOL: immutable(String[32])

balanceOf: public(HashMap[address, uint256])
allowance: public(HashMap[address, HashMap[address, uint256]])
totalSupply: public(uint256)

borrowed: public(uint256)
deposited: public(uint256)

COIN: immutable(address)
ADMIN: immutable(address)
DECIMAL_MUL: immutable(uint256)

# Compress?
prev_conv: uint256
prev_time: uint256
prev_rate: uint256

# Compresss?
model_S: public(uint256)
model_M: public(uint256)


@external
def __init__(coin: address, admin: address):
    COIN = coin
    ADMIN = admin
    NAME = concat('Curvy ', slice(ERC20(coin).name(), 0, 64-6))
    SYMBOL = concat('cl', slice(ERC20(coin).symbol(), 0, 32-2))
    DECIMAL_MUL = 10 ** (18 - ERC20(coin).decimals())
    self.prev_conv = 10**18
    self.prev_time = block.timestamp

    # Function to set these is needed TODO
    self.model_S = 15 * 10**18
    self.model_M = 3 * 10**18

    log Transfer(ZERO_ADDRESS, msg.sender, 0)


@view
@external
def coin() -> address:
    return COIN


@view
@external
def admin() -> address:
    return ADMIN


@view
@external
def name() -> String[64]:
    return NAME


@view
@external
def symbol() -> String[32]:
    return SYMBOL


@view
@external
def decimals() -> uint256:
    """
    @notice Get the number of decimals for this token
    @dev Implemented as a view method to reduce gas costs
    @return uint256 decimal places
    """
    return 18


@external
def transfer(_to : address, _value : uint256) -> bool:
    """
    @dev Transfer token for a specified address
    @param _to The address to transfer to.
    @param _value The amount to be transferred.
    """
    # NOTE: vyper does not allow underflows
    #       so the following subtraction would revert on insufficient balance
    self.balanceOf[msg.sender] -= _value
    self.balanceOf[_to] += _value

    log Transfer(msg.sender, _to, _value)
    return True


@external
def transferFrom(_from : address, _to : address, _value : uint256) -> bool:
    """
     @dev Transfer tokens from one address to another.
     @param _from address The address which you want to send tokens from
     @param _to address The address which you want to transfer to
     @param _value uint256 the amount of tokens to be transferred
    """
    self.balanceOf[_from] -= _value
    self.balanceOf[_to] += _value

    _allowance: uint256 = self.allowance[_from][msg.sender]
    if _allowance != MAX_UINT256:
        self.allowance[_from][msg.sender] = _allowance - _value

    log Transfer(_from, _to, _value)
    return True


@external
def approve(_spender : address, _value : uint256) -> bool:
    """
    @notice Approve the passed address to transfer the specified amount of
            tokens on behalf of msg.sender
    @dev Beware that changing an allowance via this method brings the risk
         that someone may use both the old and new allowance by unfortunate
         transaction ordering. This may be mitigated with the use of
         {increaseAllowance} and {decreaseAllowance}.
         https://github.com/ethereum/EIPs/issues/20#issuecomment-263524729
    @param _spender The address which will transfer the funds
    @param _value The amount of tokens that may be transferred
    @return bool success
    """
    self.allowance[msg.sender][_spender] = _value

    log Approval(msg.sender, _spender, _value)
    return True


@external
def increaseAllowance(_spender: address, _added_value: uint256) -> bool:
    """
    @notice Increase the allowance granted to `_spender` by the caller
    @dev This is alternative to {approve} that can be used as a mitigation for
         the potential race condition
    @param _spender The address which will transfer the funds
    @param _added_value The amount of to increase the allowance
    @return bool success
    """
    allowance: uint256 = self.allowance[msg.sender][_spender] + _added_value
    self.allowance[msg.sender][_spender] = allowance

    log Approval(msg.sender, _spender, allowance)
    return True


@external
def decreaseAllowance(_spender: address, _subtracted_value: uint256) -> bool:
    """
    @notice Decrease the allowance granted to `_spender` by the caller
    @dev This is alternative to {approve} that can be used as a mitigation for
         the potential race condition
    @param _spender The address which will transfer the funds
    @param _subtracted_value The amount of to decrease the allowance
    @return bool success
    """
    allowance: uint256 = self.allowance[msg.sender][_spender] - _subtracted_value
    self.allowance[msg.sender][_spender] = allowance

    log Approval(msg.sender, _spender, allowance)
    return True


@internal
@view
def _rate() -> uint256:
    M: uint256 = self.model_M  # max rate
    S: uint256 = self.model_S  # steepness

    x: uint256 = self.borrowed * 10**18
    if x > 0:
        x /= self.deposited

    # a = M / (2 * (S - 1))
    # b = (S - 1) / (S - 0.5)
    # r = a * b * x / (1 - b * x)
    bx: uint256 = (S - 10**18) * x / (S - 5 * 10**17)

    return bx * M / (2 * (S - 10**18)) / (10**18 - bx)


@external
@view
def rate() -> uint256:
    return self._rate()


@internal
@view
def _conv() -> uint256:
    return self.prev_conv + self.prev_rate * (block.timestamp - self.prev_time) / 10**18


@external
@view
def pricePerShare() -> uint256:
    return self._conv()


@external
def deposit(_value: uint256, _to: address = msg.sender) -> uint256:
    ERC20(COIN).transferFrom(msg.sender, self, _value)
    conv: uint256 = self._conv()
    self.prev_conv = conv
    self.prev_time = block.timestamp
    out: uint256 = _value * 10**18 / self._conv()

    self.totalSupply += out
    self.balanceOf[_to] += out
    self.deposited += _value
    self.prev_rate = self._rate()  # After self.deposited is changed

    log Transfer(ZERO_ADDRESS, _to, out)
    return out


@external
def withdraw(_value: uint256, _to: address = msg.sender) -> uint256:
    conv: uint256 = self._conv()
    self.prev_conv = conv
    self.prev_time = block.timestamp

    self.balanceOf[msg.sender] -= _value
    self.totalSupply -= _value
    log Transfer(msg.sender, ZERO_ADDRESS, _value)

    out: uint256 = _value * conv / 10**18
    ERC20(COIN).transfer(_to, out)
    self.deposited -= out
    self.prev_rate = self._rate()  # After self.deposited is changed

    return out


@external
def borrow(_value: uint256, _for: address):
    assert msg.sender == ADMIN

    ERC20(COIN).transfer(_for, _value)
    self.borrowed += _value
    self.prev_rate = self._rate()  # After self.borrowed is changed
