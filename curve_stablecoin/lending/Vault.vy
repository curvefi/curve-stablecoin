# pragma version 0.4.3
# pragma optimize codesize
"""
@title LlamaLend Vault
@notice ERC4626+ Vault for lending using LLAMMA algorithm
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2025 - all rights reserved
@custom:security security@curve.fi
@custom:kill Set max_supply to 0 via set_max_supply() to prevent new deposits. Existing positions can still be withdrawn.
"""

from curve_std.interfaces import IERC20
from curve_std.interfaces import IERC4626
from curve_stablecoin.interfaces import IAMM
from curve_stablecoin.interfaces import IController
from curve_stablecoin.interfaces import ILendController
from curve_stablecoin.interfaces import IFactory
from curve_stablecoin.interfaces import IVault

from curve_stablecoin import constants as c
from curve_std import token as tkn
from curve_std import math as crv_math

implements: IERC20
implements: IERC4626
implements: IVault


# These are virtual shares from method proposed by OpenZeppelin
# see: https://blog.openzeppelin.com/a-novel-defense-against-erc4626-inflation-attacks
# and
# https://github.com/OpenZeppelin/openzeppelin-curve_stablecoin/blob/master/curve_stablecoin/token/ERC20/extensions/ERC4626.sol
# redeclaration here is because: https://github.com/vyperlang/vyper/issues/4723
DEAD_SHARES: constant(uint256) = c.DEAD_SHARES
MIN_ASSETS: constant(uint256) = 10000

_borrowed_token: IERC20
# https://github.com/vyperlang/vyper/issues/4721
@external
@view
def borrowed_token() -> IERC20:
    return self._borrowed_token

_collateral_token: IERC20
# https://github.com/vyperlang/vyper/issues/4721
@external
@view
def collateral_token() -> IERC20:
    return self._collateral_token

_amm: IAMM
# https://github.com/vyperlang/vyper/issues/4721
@external
@view
def amm() -> IAMM:
    return self._amm

_controller: IController
# https://github.com/vyperlang/vyper/issues/4721
@external
@view
def controller() -> IController:
    return self._controller

_factory: IFactory
# https://github.com/vyperlang/vyper/issues/4721
@external
@view
def factory() -> IFactory:
    return self._factory


maxSupply: public(uint256)

net_deposits: public(int256)

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
        _amm: IAMM,
        _controller: IController,
        _borrowed_token: IERC20,
        _collateral_token: IERC20,
    ):
    """
    @notice Initializer for vaults
    @param _amm Address of the AMM
    @param _controller Address of the Controller
    @param _borrowed_token Token which is being borrowed
    @param _collateral_token Token which is being collateral
    """
    assert self._borrowed_token.address == empty(address)

    self._borrowed_token = _borrowed_token
    borrowed_precision: uint256 = 10**(18 - convert(staticcall _borrowed_token.decimals(), uint256))
    self._collateral_token = _collateral_token

    self._factory = IFactory(msg.sender)
    self._amm = _amm
    self._controller = _controller

    # ERC20 set up
    self.precision = borrowed_precision
    borrowed_symbol: String[32] = staticcall IERC20Symbol(_borrowed_token.address).symbol()
    self.name = concat(NAME_PREFIX, borrowed_symbol)
    # Symbol must be String[32], but we do String[34]. It doesn't affect contracts which read it (they will truncate)
    # However this will be changed as soon as Vyper can *properly* manipulate strings
    self.symbol = concat(SYMBOL_PREFIX, borrowed_symbol)

    self.maxSupply = max_value(uint256)


@external
def set_max_supply(_max_supply: uint256):
    """
    @notice Set maximum depositable supply
    """
    assert msg.sender == staticcall self._factory.admin() or msg.sender == self._factory.address
    self.maxSupply = _max_supply
    log IVault.SetMaxSupply(max_supply=_max_supply)


@external
@view
@nonreentrant
def borrow_apr() -> uint256:
    """
    @notice Borrow APR (annualized and 1e18-based)
    """
    return staticcall self._amm.rate() * (365 * 86400)


@external
@view
@nonreentrant
def lend_apr() -> uint256:
    """
    @notice Lending APR (annualized and 1e18-based)
    """
    debt: uint256 = staticcall self._controller.total_debt()
    if debt == 0:
        return 0
    return staticcall self._amm.rate() * (365 * 86400) * debt // self._total_assets()


@external
@view
def asset() -> IERC20:
    """
    @notice Asset which is the same as borrowed_token
    """
    return self._borrowed_token


@internal
@view
def _total_assets() -> uint256:
    # admin fee should be accounted for here when enabled
    return staticcall ILendController(self._controller.address).available_balance() + staticcall self._controller.total_debt()


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
def _convert_to_shares(_assets: uint256, _is_floor: bool = True,
                       _total_assets: uint256 = max_value(uint256)) -> uint256:
    total_assets: uint256 = _total_assets
    if total_assets == max_value(uint256):
        total_assets = self._total_assets()
    precision: uint256 = self.precision
    numerator: uint256 = (self.totalSupply + DEAD_SHARES) * _assets * precision
    denominator: uint256 = (total_assets * precision + 1)
    if _is_floor:
        return numerator // denominator
    else:
        return crv_math.div_up(numerator, denominator)


@internal
@view
def _convert_to_assets(_shares: uint256, _is_floor: bool = True,
                       _total_assets: uint256 = max_value(uint256)) -> uint256:
    total_assets: uint256 = _total_assets
    if total_assets == max_value(uint256):
        total_assets = self._total_assets()
    precision: uint256 = self.precision
    numerator: uint256 = _shares * (total_assets * precision + 1)
    denominator: uint256 = (self.totalSupply + DEAD_SHARES) * precision
    if _is_floor:
        return numerator // denominator
    else:
        return crv_math.div_up(numerator, denominator)


@external
@view
@nonreentrant
def pricePerShare(_is_floor: bool = True) -> uint256:
    """
    @notice Method which shows how much one pool share costs in asset tokens if they are normalized to 18 decimals
    @dev pricePerShare can decrease if totalSupply reaches zero (e.g., when all shares are burned).
         In this case, it resets to the initial value.
    """
    supply: uint256 = self.totalSupply
    if supply == 0:
        return 10**18 // DEAD_SHARES
    else:
        precision: uint256 = self.precision
        numerator: uint256 = 10**18 * (self._total_assets() * precision + 1)
        denominator: uint256 = (supply + DEAD_SHARES)
        pps: uint256 = 0
        if _is_floor:
            pps = numerator // denominator
        else:
            pps = crv_math.div_up(numerator, denominator)
        assert pps > 0
        return pps


@external
@view
@nonreentrant
def convertToShares(_assets: uint256) -> uint256:
    """
    @notice Returns the amount of shares which the Vault would exchange for the given amount of shares provided
    """
    return self._convert_to_shares(_assets)


@external
@view
@nonreentrant
def convertToAssets(_shares: uint256) -> uint256:
    """
    @notice Returns the amount of assets that the Vault would exchange for the amount of shares provided
    """
    return self._convert_to_assets(_shares)


@external
@view
def maxDeposit(_receiver: address) -> uint256:
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
def previewDeposit(_assets: uint256) -> uint256:
    """
    @notice Returns the amount of shares which can be obtained upon depositing assets
    """
    return self._convert_to_shares(_assets)


# TODO Statemind AI INFORMATIONAL-02
@external
@nonreentrant
def deposit(_assets: uint256, _receiver: address = msg.sender) -> uint256:
    """
    @notice Deposit assets in return for whatever number of shares corresponds to the current conditions
    @param _assets Amount of assets to deposit
    @param _receiver Receiver of the shares who is optional. If not specified - receiver is the sender
    """
    controller: IController = self._controller
    total_assets: uint256 = self._total_assets()
    assert total_assets + _assets >= MIN_ASSETS, "Need more assets"
    assert total_assets + _assets <= self.maxSupply, "Supply limit"
    to_mint: uint256 = self._convert_to_shares(_assets, True, total_assets)
    tkn.transfer_from(self._borrowed_token, msg.sender, controller.address, _assets)
    self.net_deposits += convert(_assets, int256)
    self._mint(_receiver, to_mint)
    extcall controller.save_rate()
    log IERC4626.Deposit(sender=msg.sender, owner=_receiver, assets=_assets, shares=to_mint)
    return to_mint


@external
@view
def maxMint(_receiver: address) -> uint256:
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
def previewMint(_shares: uint256) -> uint256:
    """
    @notice Calculate the amount of assets which is needed to exactly mint the given amount of shares
    """
    return self._convert_to_assets(_shares, False)


# TODO Statemind AI INFORMATIONAL-02
@external
@nonreentrant
def mint(_shares: uint256, _receiver: address = msg.sender) -> uint256:
    """
    @notice Mint given amount of shares taking whatever number of assets it requires
    @param _shares Number of sharess to mint
    @param _receiver Optional receiver for the shares. If not specified - it's the sender
    """
    controller: IController = self._controller
    total_assets: uint256 = self._total_assets()
    assets: uint256 = self._convert_to_assets(_shares, False, total_assets)
    assert total_assets + assets >= MIN_ASSETS, "Need more assets"
    assert total_assets + assets <= self.maxSupply, "Supply limit"
    tkn.transfer_from(self._borrowed_token, msg.sender, controller.address, assets)
    self.net_deposits += convert(assets, int256)
    self._mint(_receiver, _shares)
    extcall controller.save_rate()
    log IERC4626.Deposit(sender=msg.sender, owner=_receiver, assets=assets, shares=_shares)
    return assets


@external
@view
@nonreentrant
def maxWithdraw(_owner: address) -> uint256:
    """
    @notice Maximum amount of assets which a given user can withdraw. Aware of both user's balance and available liquidity
    """
    return min(
        self._convert_to_assets(self.balanceOf[_owner]),
        staticcall ILendController(self._controller.address).available_balance())


@external
@view
@nonreentrant
def previewWithdraw(_assets: uint256) -> uint256:
    """
    @notice Calculate number of shares which gets burned when withdrawing given amount of asset
    """
    return self._convert_to_shares(_assets, False)


@external
@nonreentrant
def withdraw(_assets: uint256, _receiver: address = msg.sender, _owner: address = msg.sender) -> uint256:
    """
    @notice Withdraw given amount of asset and burn the corresponding amount of vault shares
    @param _assets Amount of assets to withdraw
    @param _receiver Receiver of the assets (optional, sender if not specified)
    @param _owner Owner who's shares the caller takes. Only can take those if owner gave the approval to the sender. Optional
    """
    total_assets: uint256 = self._total_assets()
    assert total_assets - _assets >= MIN_ASSETS or total_assets == _assets, "Need more assets"
    shares: uint256 = self._convert_to_shares(_assets, False, total_assets)
    if _owner != msg.sender:
        allowance: uint256 = self.allowance[_owner][msg.sender]
        if allowance != max_value(uint256):
            self._approve(_owner, msg.sender, allowance - shares)

    controller: IController = self._controller
    self._burn(_owner, shares)
    tkn.transfer_from(self._borrowed_token, controller.address, _receiver, _assets)
    self.net_deposits -= convert(_assets, int256)
    extcall controller.save_rate()
    log IERC4626.Withdraw(sender=msg.sender, receiver=_receiver, owner=_owner, assets=_assets, shares=shares)
    return shares


@external
@view
@nonreentrant
def maxRedeem(_owner: address) -> uint256:
    """
    @notice Calculate maximum amount of shares which a given user can redeem
    """
    return min(
        self._convert_to_shares(staticcall ILendController(self._controller.address).available_balance(), False),
        self.balanceOf[_owner])


@external
@view
@nonreentrant
def previewRedeem(_shares: uint256) -> uint256:
    """
    @notice Calculate the amount of assets which can be obtained by redeeming the given amount of shares
    """
    return self._convert_to_assets(_shares)


@external
@nonreentrant
def redeem(_shares: uint256, _receiver: address = msg.sender, _owner: address = msg.sender) -> uint256:
    """
    @notice Burn given amount of shares and give corresponding assets to the user
    @param _shares Amount of shares to burn
    @param _receiver Optional receiver of the assets
    @param _owner Optional owner of the shares. Can only redeem if owner gave approval to the sender
    """
    if _owner != msg.sender:
        allowance: uint256 = self.allowance[_owner][msg.sender]
        if allowance != max_value(uint256):
            self._approve(_owner, msg.sender, allowance - _shares)

    total_assets: uint256 = self._total_assets()
    assets_to_redeem: uint256 = self._convert_to_assets(_shares, True, total_assets)
    if total_assets - assets_to_redeem < MIN_ASSETS:
        if _shares == self.totalSupply:
            # This is the last withdrawal, so we can take everything
            assets_to_redeem = total_assets
        else:
            raise "Need more assets"
    self._burn(_owner, _shares)
    controller: IController = self._controller
    tkn.transfer_from(self._borrowed_token, controller.address, _receiver, assets_to_redeem)
    self.net_deposits -= convert(assets_to_redeem, int256)
    extcall controller.save_rate()
    log IERC4626.Withdraw(sender=msg.sender, receiver=_receiver, owner=_owner, assets=assets_to_redeem, shares=_shares)
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
    return staticcall self._factory.admin()
