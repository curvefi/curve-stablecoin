# pragma version 0.4.3
# pragma optimize codesize
"""
@title LlamaLend Vault
@notice ERC4626+ Vault for lending using LLAMMA algorithm
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2025 - all rights reserved
"""

from contracts.interfaces import IERC20
from contracts.interfaces import IERC4626
from contracts.interfaces import IAMM
from contracts.interfaces import ILlamalendController as IController
from contracts.interfaces import IFactory

from contracts import constants as c

implements: IERC20
implements: IERC4626


event SetMaxSupply:
    max_supply: uint256

# These are virtual shares from method proposed by OpenZeppelin
# see: https://blog.openzeppelin.com/a-novel-defense-against-erc4626-inflation-attacks
# and
# https://github.com/OpenZeppelin/openzeppelin-contracts/blob/master/contracts/token/ERC20/extensions/ERC4626.sol
DEAD_SHARES: constant(uint256) = c.DEAD_SHARES
MIN_ASSETS: constant(uint256) = 10000

borrowed_token: public(IERC20)
collateral_token: public(IERC20)

amm: public(IAMM)
controller: public(IController)
factory: public(IFactory)

maxSupply: public(uint256)

asset_balance: public(uint256)

# ERC20 publics

decimals: public(constant(uint8)) = 18
name: public(String[64])
symbol: public(String[34])

NAME_PREFIX: constant(String[16]) = 'Curve Vault for '
SYMBOL_PREFIX: constant(String[2]) = 'cv'

allowance: public(HashMap[address, HashMap[address, uint256]])
balanceOf: public(HashMap[address, uint256])
totalSupply: public(uint256)

precision: uint256

# Only needed for initialize
interface IERC20Symbol:
    def symbol() -> String[32]: view

@external
def initialize(
        amm: IAMM,
        controller: IController,
        borrowed_token: IERC20,
        collateral_token: IERC20,
    ):
    """
    @notice Initializer for vaults
    @param amm Address of the AMM
    @param controller Address of the Controller
    @param borrowed_token Token which is being borrowed
    @param collateral_token Token which is being collateral
    """
    self.borrowed_token = borrowed_token
    borrowed_precision: uint256 = 10**(18 - convert(staticcall borrowed_token.decimals(), uint256))
    self.collateral_token = collateral_token

    self.factory = IFactory(msg.sender)
    self.amm = amm
    self.controller = controller

    # ERC20 set up
    self.precision = borrowed_precision
    borrowed_symbol: String[32] = staticcall IERC20Symbol(borrowed_token.address).symbol()
    self.name = concat(NAME_PREFIX, borrowed_symbol)
    # Symbol must be String[32], but we do String[34]. It doesn't affect contracts which read it (they will truncate)
    # However this will be changed as soon as Vyper can *properly* manipulate strings
    self.symbol = concat(SYMBOL_PREFIX, borrowed_symbol)

    self.maxSupply = max_value(uint256)


@external
def set_max_supply(max_supply: uint256):
    """
    @notice Set maximum depositable supply
    """
    assert msg.sender == staticcall self.factory.admin() or msg.sender == self.factory.address
    self.maxSupply = max_supply
    log SetMaxSupply(max_supply=max_supply)


@external
@view
@nonreentrant
def borrow_apr() -> uint256:
    """
    @notice Borrow APR (annualized and 1e18-based)
    """
    return staticcall self.amm.rate() * (365 * 86400)


@external
@view
@nonreentrant
def lend_apr() -> uint256:
    """
    @notice Lending APR (annualized and 1e18-based)
    """
    debt: uint256 = staticcall self.controller.total_debt()
    if debt == 0:
        return 0
    return staticcall self.amm.rate() * (365 * 86400) * debt // self._total_assets()


@external
@view
def asset() -> IERC20:
    """
    @notice Asset which is the same as borrowed_token
    """
    return self.borrowed_token


@internal
@view
def _total_assets() -> uint256:
    # admin fee should be accounted for here when enabled
    return staticcall self.controller.borrowed_balance() + staticcall self.controller.total_debt()


@external
@view
@nonreentrant
def totalAssets() -> uint256:
    """
    @notice Total assets which can be lent out or be in reserve
    """
    return self._total_assets()


@internal
@view
def _convert_to_shares(assets: uint256, is_floor: bool = True,
                       _total_assets: uint256 = max_value(uint256)) -> uint256:
    total_assets: uint256 = _total_assets
    if total_assets == max_value(uint256):
        total_assets = self._total_assets()
    precision: uint256 = self.precision
    numerator: uint256 = (self.totalSupply + DEAD_SHARES) * assets * precision
    denominator: uint256 = (total_assets * precision + 1)
    if is_floor:
        return numerator // denominator
    else:
        return (numerator + denominator - 1) // denominator


@internal
@view
def _convert_to_assets(shares: uint256, is_floor: bool = True,
                       _total_assets: uint256 = max_value(uint256)) -> uint256:
    total_assets: uint256 = _total_assets
    if total_assets == max_value(uint256):
        total_assets = self._total_assets()
    precision: uint256 = self.precision
    numerator: uint256 = shares * (total_assets * precision + 1)
    denominator: uint256 = (self.totalSupply + DEAD_SHARES) * precision
    if is_floor:
        return numerator // denominator
    else:
        return (numerator + denominator - 1) // denominator


@external
@view
@nonreentrant
def pricePerShare(is_floor: bool = True) -> uint256:
    """
    @notice Method which shows how much one pool share costs in asset tokens if they are normalized to 18 decimals
    """
    supply: uint256 = self.totalSupply
    if supply == 0:
        return 10**18 // DEAD_SHARES
    else:
        precision: uint256 = self.precision
        numerator: uint256 = 10**18 * (self._total_assets() * precision + 1)
        denominator: uint256 = (supply + DEAD_SHARES)
        pps: uint256 = 0
        if is_floor:
            pps = numerator // denominator
        else:
            pps = (numerator + denominator - 1) // denominator
        assert pps > 0
        return pps


@external
@view
@nonreentrant
def convertToShares(assets: uint256) -> uint256:
    """
    @notice Returns the amount of shares which the Vault would exchange for the given amount of shares provided
    """
    return self._convert_to_shares(assets)


@external
@view
@nonreentrant
def convertToAssets(shares: uint256) -> uint256:
    """
    @notice Returns the amount of assets that the Vault would exchange for the amount of shares provided
    """
    return self._convert_to_assets(shares)


@external
@view
def maxDeposit(receiver: address) -> uint256:
    """
    @notice Maximum amount of assets which a given user can deposit (inf)
    """
    max_supply: uint256 = self.maxSupply
    if max_supply == max_value(uint256):
        return max_supply
    else:
        assets: uint256 = self._total_assets()
        return max(max_supply, assets) - assets


@external
@view
@nonreentrant
def previewDeposit(assets: uint256) -> uint256:
    """
    @notice Returns the amount of shares which can be obtained upon depositing assets
    """
    return self._convert_to_shares(assets)


@external
@nonreentrant
def deposit(assets: uint256, receiver: address = msg.sender) -> uint256:
    """
    @notice Deposit assets in return for whatever number of shares corresponds to the current conditions
    @param assets Amount of assets to deposit
    @param receiver Receiver of the shares who is optional. If not specified - receiver is the sender
    """
    controller: IController = self.controller
    total_assets: uint256 = self._total_assets()
    assert total_assets + assets >= MIN_ASSETS, "Need more assets"
    assert total_assets + assets <= self.maxSupply, "Supply limit"
    to_mint: uint256 = self._convert_to_shares(assets, True, total_assets)
    assert extcall self.borrowed_token.transferFrom(msg.sender, controller.address, assets, default_return_value=True)
    self.asset_balance += assets
    self._mint(receiver, to_mint)
    extcall controller.save_rate()
    log IERC4626.Deposit(sender=msg.sender, owner=receiver, assets=assets, shares=to_mint)
    return to_mint


@external
@view
def maxMint(receiver: address) -> uint256:
    """
    @notice Return maximum amount of shares which a given user can mint (inf)
    """
    max_supply: uint256 = self.maxSupply
    if max_supply == max_value(uint256):
        return max_supply
    else:
        assets: uint256 = self._total_assets()
        return self._convert_to_shares(max(max_supply, assets) - assets)


@external
@view
@nonreentrant
def previewMint(shares: uint256) -> uint256:
    """
    @notice Calculate the amount of assets which is needed to exactly mint the given amount of shares
    """
    return self._convert_to_assets(shares, False)


@external
@nonreentrant
def mint(shares: uint256, receiver: address = msg.sender) -> uint256:
    """
    @notice Mint given amount of shares taking whatever number of assets it requires
    @param shares Number of sharess to mint
    @param receiver Optional receiver for the shares. If not specified - it's the sender
    """
    controller: IController = self.controller
    total_assets: uint256 = self._total_assets()
    assets: uint256 = self._convert_to_assets(shares, False, total_assets)
    assert total_assets + assets >= MIN_ASSETS, "Need more assets"
    assert total_assets + assets <= self.maxSupply, "Supply limit"
    assert extcall self.borrowed_token.transferFrom(msg.sender, controller.address, assets, default_return_value=True)
    self.asset_balance += assets
    self._mint(receiver, shares)
    extcall controller.save_rate()
    log IERC4626.Deposit(sender=msg.sender, owner=receiver, assets=assets, shares=shares)
    return assets


@external
@view
@nonreentrant
def maxWithdraw(owner: address) -> uint256:
    """
    @notice Maximum amount of assets which a given user can withdraw. Aware of both user's balance and available liquidity
    """
    return min(
        self._convert_to_assets(self.balanceOf[owner]),
        staticcall self.controller.borrowed_balance())


@external
@view
@nonreentrant
def previewWithdraw(assets: uint256) -> uint256:
    """
    @notice Calculate number of shares which gets burned when withdrawing given amount of asset
    """
    assert assets <= staticcall self.controller.borrowed_balance()
    return self._convert_to_shares(assets, False)


@external
@nonreentrant
def withdraw(assets: uint256, receiver: address = msg.sender, owner: address = msg.sender) -> uint256:
    """
    @notice Withdraw given amount of asset and burn the corresponding amount of vault shares
    @param assets Amount of assets to withdraw
    @param receiver Receiver of the assets (optional, sender if not specified)
    @param owner Owner who's shares the caller takes. Only can take those if owner gave the approval to the sender. Optional
    """
    total_assets: uint256 = self._total_assets()
    assert total_assets - assets >= MIN_ASSETS or total_assets == assets, "Need more assets"
    shares: uint256 = self._convert_to_shares(assets, False, total_assets)
    if owner != msg.sender:
        allowance: uint256 = self.allowance[owner][msg.sender]
        if allowance != max_value(uint256):
            self._approve(owner, msg.sender, allowance - shares)

    controller: IController = self.controller
    self._burn(owner, shares)
    assert extcall self.borrowed_token.transferFrom(controller.address, receiver, assets, default_return_value=True)
    self.asset_balance -= assets
    extcall controller.save_rate()
    log IERC4626.Withdraw(sender=msg.sender, receiver=receiver, owner=owner, assets=assets, shares=shares)
    return shares


@external
@view
@nonreentrant
def maxRedeem(owner: address) -> uint256:
    """
    @notice Calculate maximum amount of shares which a given user can redeem
    """
    return min(
        self._convert_to_shares(staticcall self.controller.borrowed_balance(), False),
        self.balanceOf[owner])


@external
@view
@nonreentrant
def previewRedeem(shares: uint256) -> uint256:
    """
    @notice Calculate the amount of assets which can be obtained by redeeming the given amount of shares
    """
    if self.totalSupply == 0:
        assert shares == 0
        return 0

    else:
        assets_to_redeem: uint256 = self._convert_to_assets(shares)
        assert assets_to_redeem <= staticcall self.controller.borrowed_balance()
        return assets_to_redeem


@external
@nonreentrant
def redeem(shares: uint256, receiver: address = msg.sender, owner: address = msg.sender) -> uint256:
    """
    @notice Burn given amount of shares and give corresponding assets to the user
    @param shares Amount of shares to burn
    @param receiver Optional receiver of the assets
    @param owner Optional owner of the shares. Can only redeem if owner gave approval to the sender
    """
    if owner != msg.sender:
        allowance: uint256 = self.allowance[owner][msg.sender]
        if allowance != max_value(uint256):
            self._approve(owner, msg.sender, allowance - shares)

    total_assets: uint256 = self._total_assets()
    assets_to_redeem: uint256 = self._convert_to_assets(shares, True, total_assets)
    if total_assets - assets_to_redeem < MIN_ASSETS:
        if shares == self.totalSupply:
            # This is the last withdrawal, so we can take everything
            assets_to_redeem = total_assets
        else:
            raise "Need more assets"
    self._burn(owner, shares)
    controller: IController = self.controller
    assert extcall self.borrowed_token.transferFrom(controller.address, receiver, assets_to_redeem, default_return_value=True)
    self.asset_balance -= assets_to_redeem
    extcall controller.save_rate()
    log IERC4626.Withdraw(sender=msg.sender, receiver=receiver, owner=owner, assets=assets_to_redeem, shares=shares)
    return assets_to_redeem


# ERC20 methods

@internal
def _approve(_owner: address, _spender: address, _value: uint256):
    self.allowance[_owner][_spender] = _value

    log IERC20.Approval(owner=_owner, spender=_spender, value=_value)


@internal
def _burn(_from: address, _value: uint256):
    self.balanceOf[_from] -= _value
    self.totalSupply -= _value

    log IERC20.Transfer(sender=_from, receiver=empty(address), value=_value)


@internal
def _mint(_to: address, _value: uint256):
    self.balanceOf[_to] += _value
    self.totalSupply += _value

    log IERC20.Transfer(sender=empty(address), receiver=_to, value=_value)


@internal
def _transfer(_from: address, _to: address, _value: uint256):
    assert _to not in [self, empty(address)]

    self.balanceOf[_from] -= _value
    self.balanceOf[_to] += _value

    log IERC20.Transfer(sender=_from, receiver=_to, value=_value)


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
@view
def admin() -> address:
    return staticcall self.factory.admin()
