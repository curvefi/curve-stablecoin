# @version 0.3.10
"""
@title Vault
@notice ERC4626+ Vault for lending with crvUSD using LLAMMA algorithm
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
"""
from vyper.interfaces import ERC20 as ERC20Spec
from vyper.interfaces import ERC20Detailed


implements: ERC20Spec
implements: ERC20Detailed


interface ERC20:
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable
    def transfer(_to: address, _value: uint256) -> bool: nonpayable
    def decimals() -> uint256: view
    def balanceOf(_from: address) -> uint256: view
    def symbol() -> String[32]: view
    def name() -> String[64]: view

interface AMM:
    def set_admin(_admin: address): nonpayable
    def rate() -> uint256: view

interface Controller:
    def total_debt() -> uint256: view
    def minted() -> uint256: view
    def redeemed() -> uint256: view
    def monetary_policy() -> address: view
    def check_lock() -> bool: view

interface PriceOracle:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable

interface MonetaryPolicy:
    def rate_write(controller: address) -> uint256: nonpayable

interface Factory:
    def admin() -> address: view


# ERC20 events

event Approval:
    owner: indexed(address)
    spender: indexed(address)
    value: uint256

event Transfer:
    sender: indexed(address)
    receiver: indexed(address)
    value: uint256

# ERC4626 events

event Deposit:
    sender: indexed(address)
    owner: indexed(address)
    assets: uint256
    shares: uint256

event Withdraw:
    sender: indexed(address)
    receiver: indexed(address)
    owner: indexed(address)
    assets: uint256
    shares: uint256


# Limits
MIN_A: constant(uint256) = 2
MAX_A: constant(uint256) = 10000
MIN_FEE: constant(uint256) = 10**6  # 1e-12, still needs to be above 0
MAX_FEE: constant(uint256) = 10**17  # 10%
MAX_LOAN_DISCOUNT: constant(uint256) = 5 * 10**17
MIN_LIQUIDATION_DISCOUNT: constant(uint256) = 10**16
ADMIN_FEE: constant(uint256) = 0

# These are virtual shares from method proposed by OpenZeppelin
# see: https://blog.openzeppelin.com/a-novel-defense-against-erc4626-inflation-attacks
# and
# https://github.com/OpenZeppelin/openzeppelin-contracts/blob/master/contracts/token/ERC20/extensions/ERC4626.sol
DEAD_SHARES: constant(uint256) = 1000

borrowed_token: public(ERC20)
collateral_token: public(ERC20)

price_oracle: public(PriceOracle)
amm: public(AMM)
controller: public(Controller)
factory: public(Factory)


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


@external
def __init__():
    """
    @notice Template for Vault implementation
    @param stablecoin Stablecoin address to test if it is borrowed or lent out token
    """
    # The contract is made a "normal" template (not blueprint) so that we can get contract address before init
    # This is needed if we want to create a rehypothecation dual-market with two vaults
    # where vaults are collaterals of each other
    self.borrowed_token = ERC20(0x0000000000000000000000000000000000000001)


@internal
@pure
def ln_int(_x: uint256) -> int256:
    """
    @notice Logarithm ln() function based on log2. Not very gas-efficient but brief
    """
    # adapted from: https://medium.com/coinmonks/9aef8515136e
    # and vyper log implementation
    # This can be much more optimal but that's not important here
    x: uint256 = _x
    res: uint256 = 0
    for i in range(8):
        t: uint256 = 2**(7 - i)
        p: uint256 = 2**t
        if x >= p * 10**18:
            x /= p
            res += t * 10**18
    d: uint256 = 10**18
    for i in range(59):  # 18 decimals: math.log2(10**10) == 59.7
        if (x >= 2 * 10**18):
            res += d
            x /= 2
        x = x * x / 10**18
        d /= 2
    # Now res = log2(x)
    # ln(x) = log2(x) / log2(e)
    return convert(res * 10**18 / 1442695040888963328, int256)


@external
def initialize(
        amm_impl: address,
        controller_impl: address,
        borrowed_token: ERC20,
        collateral_token: ERC20,
        A: uint256,
        fee: uint256,
        price_oracle: PriceOracle,  # Factory makes from template if needed, deploying with a from_pool()
        monetary_policy: address,  # Standard monetary policy set in factory
        loan_discount: uint256,
        liquidation_discount: uint256
    ) -> (address, address):
    """
    @notice Initializer for vaults
    @param amm_impl AMM implementation (blueprint)
    @param controller_impl Controller implementation (blueprint)
    @param borrowed_token Token which is being borrowed
    @param collateral_token Token used for collateral
    @param A Amplification coefficient: band size is ~1/A
    @param fee Fee for swaps in AMM (for ETH markets found to be 0.6%)
    @param price_oracle Already initialized price oracle
    @param monetary_policy Already initialized monetary policy
    @param loan_discount Maximum discount. LTV = sqrt(((A - 1) / A) ** 4) - loan_discount
    @param liquidation_discount Liquidation discount. LT = sqrt(((A - 1) / A) ** 4) - liquidation_discount
    """
    assert self.borrowed_token.address == empty(address)

    self.borrowed_token = borrowed_token
    self.collateral_token = collateral_token
    self.price_oracle = price_oracle

    assert A >= MIN_A and A <= MAX_A, "Wrong A"
    assert fee <= MAX_FEE, "Fee too high"
    assert fee >= MIN_FEE, "Fee too low"
    assert liquidation_discount >= MIN_LIQUIDATION_DISCOUNT, "Liquidation discount too low"
    assert loan_discount <= MAX_LOAN_DISCOUNT, "Loan discount too high"
    assert loan_discount > liquidation_discount, "need loan_discount>liquidation_discount"

    p: uint256 = price_oracle.price()  # This also validates price oracle ABI
    assert p > 0
    assert price_oracle.price_w() == p
    A_ratio: uint256 = 10**18 * A / (A - 1)

    borrowed_precision: uint256 = 10**(18 - borrowed_token.decimals())

    amm: address = create_from_blueprint(
        amm_impl,
        borrowed_token.address, borrowed_precision,
        collateral_token.address, 10**(18 - collateral_token.decimals()),
        A, isqrt(A_ratio * 10**18), self.ln_int(A_ratio),
        p, fee, ADMIN_FEE, price_oracle.address,
        code_offset=3)
    controller: address = create_from_blueprint(
        controller_impl,
        empty(address), monetary_policy, loan_discount, liquidation_discount, amm,
        code_offset=3)
    AMM(amm).set_admin(controller)

    self.amm = AMM(amm)
    self.controller = Controller(controller)
    self.factory = Factory(msg.sender)

    # ERC20 set up
    self.precision = borrowed_precision
    borrowed_symbol: String[32] = borrowed_token.symbol()
    self.name = concat(NAME_PREFIX, borrowed_symbol)
    # Symbol must be String[32], but we do String[34]. It doesn't affect contracts which read it (they will truncate)
    # However this will be changed as soon as Vyper can *properly* manipulate strings
    self.symbol = concat(SYMBOL_PREFIX, borrowed_symbol)

    # No events because it's the only market we would ever create in this contract

    return controller, amm


@internal
def _update_rates(controller: address):
    MonetaryPolicy(self.controller.monetary_policy()).rate_write(controller)


@external
@view
@nonreentrant('lock')
def borrow_apr() -> uint256:
    """
    @notice Borrow APR (annualized and 1e18-based)
    """
    return self.amm.rate() * (365 * 86400)


@external
@view
@nonreentrant('lock')
def lend_apr() -> uint256:
    """
    @notice Lending APR (annualized and 1e18-based)
    """
    debt: uint256 = self.controller.total_debt()
    if debt == 0:
        return 0
    else:
        return self.amm.rate() * (365 * 86400) * debt / self._total_assets()


@external
@view
def asset() -> ERC20:
    """
    @notice Asset which is the same as borrowed_token
    """
    return self.borrowed_token


@internal
@view
def _total_assets() -> uint256:
    # admin fee should be accounted for here when enabled
    self.controller.check_lock()
    return self.borrowed_token.balanceOf(self.controller.address) + self.controller.total_debt()


@external
@view
@nonreentrant('lock')
def totalAssets() -> uint256:
    """
    @notice Total assets which can be lent out or be in reserve
    """
    return self._total_assets()


@internal
@view
def _convert_to_shares(assets: uint256, is_floor: bool = True) -> uint256:
    precision: uint256 = self.precision
    numerator: uint256 = (self.totalSupply + DEAD_SHARES) * assets * precision
    denominator: uint256 = (self._total_assets() * precision + 1)
    if is_floor:
        return numerator / denominator
    else:
        return (numerator + denominator - 1) / denominator


@internal
@view
def _convert_to_assets(shares: uint256, is_floor: bool = True) -> uint256:
    precision: uint256 = self.precision
    numerator: uint256 = shares * (self._total_assets() * precision + 1)
    denominator: uint256 = (self.totalSupply + DEAD_SHARES) * precision
    if is_floor:
        return numerator / denominator
    else:
        return (numerator + denominator - 1) / denominator


@external
@view
@nonreentrant('lock')
def pricePerShare(is_floor: bool = True) -> uint256:
    """
    @notice Method which shows how much one pool share costs in asset tokens
    """
    supply: uint256 = self.totalSupply
    if supply == 0:
        return 10**18 / DEAD_SHARES
    else:
        precision: uint256 = self.precision
        numerator: uint256 = 10**18 * (self._total_assets() * precision + 1)
        denominator: uint256 = (supply + DEAD_SHARES)
        if is_floor:
            return numerator / denominator
        else:
            return (numerator + denominator - 1) / denominator


@external
@view
@nonreentrant('lock')
def convertToShares(assets: uint256) -> uint256:
    """
    @notice Returns the amount of shares which the Vault would exchange for the given amount of shares provided
    """
    return self._convert_to_shares(assets)


@external
@view
@nonreentrant('lock')
def convertToAssets(shares: uint256) -> uint256:
    """
    @notice Returns the amount of assets that the Vault would exchange for the amount of shares provided
    """
    return self._convert_to_assets(shares)


@external
@view
def maxDeposit(receiver: address) -> uint256:
    """
    @notice Maximum amount which can be deposited is unlimited
    """
    return max_value(uint256)


@external
@view
@nonreentrant('lock')
def previewDeposit(assets: uint256) -> uint256:
    """
    @notice Returns the amount of shares which can be obtained upon depositing assets
    """
    return self._convert_to_shares(assets)


@external
@nonreentrant('lock')
def deposit(assets: uint256, receiver: address = msg.sender) -> uint256:
    """
    @notice Deposit assets in return for whatever number of shares corresponds to the current conditions
    @param assets Amount of assets to deposit
    @param receiver Receiver of the shares who is optional. If not specified - receiver is the sender
    """
    controller: address = self.controller.address
    to_mint: uint256 = self._convert_to_shares(assets)
    assert self.borrowed_token.transferFrom(msg.sender, controller, assets, default_return_value=True)
    self._mint(receiver, to_mint)
    self._update_rates(controller)
    log Deposit(msg.sender, receiver, assets, to_mint)
    return to_mint


@external
@view
def maxMint(receiver: address) -> uint256:
    """
    @notice Maximum amount which can be minted (infinity)
    """
    return max_value(uint256)


@external
@view
@nonreentrant('lock')
def previewMint(shares: uint256) -> uint256:
    """
    @notice Calculate the amount of assets which is needed to exactly mint the given amount of shares
    """
    return self._convert_to_assets(shares, False)


@external
@nonreentrant('lock')
def mint(shares: uint256, receiver: address = msg.sender) -> uint256:
    """
    @notice Mint given amount of shares taking whatever number of assets it requires
    @param shares Number of sharess to mint
    @param receiver Optional receiver for the shares. If not specified - it's the sender
    """
    controller: address = self.controller.address
    assets: uint256 = self._convert_to_assets(shares, False)
    assert self.borrowed_token.transferFrom(msg.sender, controller, assets, default_return_value=True)
    self._mint(receiver, shares)
    self._update_rates(controller)
    log Deposit(msg.sender, receiver, assets, shares)
    return assets


@external
@view
@nonreentrant('lock')
def maxWithdraw(owner: address) -> uint256:
    """
    @notice Maximum amount of assets which a given user can withdraw. Aware of both user's balance and available liquidity
    """
    return min(
        self._convert_to_assets(self.balanceOf[owner]),
        self.borrowed_token.balanceOf(self.controller.address))


@external
@view
@nonreentrant('lock')
def previewWithdraw(assets: uint256) -> uint256:
    """
    @notice Calculate number of shares which gets burned when withdrawing given amount of asset
    """
    assert assets <= self.borrowed_token.balanceOf(self.controller.address)
    return self._convert_to_shares(assets, False)


@external
@nonreentrant('lock')
def withdraw(assets: uint256, receiver: address = msg.sender, owner: address = msg.sender) -> uint256:
    """
    @notice Withdraw given amount of asset and burn the corresponding amount of vault shares
    @param assets Amount of assets to withdraw
    @param receiver Receiver of the assets (optional, sender if not specified)
    @param owner Owner who's shares the caller takes. Only can take those if owner gave the approval to the sender. Optional
    """
    shares: uint256 = self._convert_to_shares(assets, False)
    if owner != msg.sender:
        allowance: uint256 = self.allowance[owner][msg.sender]
        if allowance != max_value(uint256):
            self._approve(owner, msg.sender, allowance - shares)

    controller: address = self.controller.address
    self._burn(owner, shares)
    assert self.borrowed_token.transferFrom(controller, receiver, assets, default_return_value=True)
    self._update_rates(controller)
    log Withdraw(msg.sender, receiver, owner, assets, shares)
    return shares


@external
@view
@nonreentrant('lock')
def maxRedeem(owner: address) -> uint256:
    """
    @notice Calculate maximum amount of shares which a given user can redeem
    """
    return min(
        self._convert_to_shares(self.borrowed_token.balanceOf(self.controller.address), False),
        self.balanceOf[owner])


@external
@view
@nonreentrant('lock')
def previewRedeem(shares: uint256) -> uint256:
    """
    @notice Calculate the amount of assets which can be obtained by redeeming the given amount of shares
    """
    if self.totalSupply == 0:
        assert shares == 0
        return 0

    else:
        assets_to_redeem: uint256 = self._convert_to_assets(shares)
        assert assets_to_redeem <= self.borrowed_token.balanceOf(self.controller.address)
        return assets_to_redeem


@external
@nonreentrant('lock')
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

    assets_to_redeem: uint256 = self._convert_to_assets(shares)
    self._burn(owner, shares)
    controller: address = self.controller.address
    assert self.borrowed_token.transferFrom(controller, receiver, assets_to_redeem, default_return_value=True)
    self._update_rates(controller)
    log Withdraw(msg.sender, receiver, owner, assets_to_redeem, shares)
    return assets_to_redeem


# ERC20 methods

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
def _mint(_to: address, _value: uint256):
    self.balanceOf[_to] += _value
    self.totalSupply += _value

    log Transfer(empty(address), _to, _value)


@internal
def _transfer(_from: address, _to: address, _value: uint256):
    assert _to not in [self, empty(address)]

    self.balanceOf[_from] -= _value
    self.balanceOf[_to] += _value

    log Transfer(_from, _to, _value)


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
    return self.factory.admin()
