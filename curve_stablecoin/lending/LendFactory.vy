# pragma version 0.4.3
# pragma nonreentrancy on
"""
@title LlamaLend Factory
@notice Factory for one-way lending markets powered by LlamaLend AMM
@author Curve.fi
@license Copyright (c) Curve.Fi, 2020-2025 - all rights reserved
@custom:security security@curve.fi
"""

from curve_std.interfaces import IERC20

from curve_stablecoin.interfaces import IVault
from curve_stablecoin.interfaces import IController
from curve_stablecoin.interfaces import IAMM
from curve_stablecoin.interfaces import IPriceOracle
from curve_stablecoin.interfaces import ILendFactory
from curve_stablecoin.interfaces import IMonetaryPolicy

from ownership_proxy.interfaces import IProxy

implements: ILendFactory

from snekmate.utils import math
from snekmate.auth import ownable
from curve_stablecoin import constants as c

initializes: ownable

exports: (
    # `owner` is not exported as we refer to it as `admin` for backwards compatibility
    # `renounce_ownership` is intentionally not exported
    ownable.transfer_ownership,
)


MIN_A: constant(uint256) = 2
MAX_A: constant(uint256) = 10000
MIN_FEE: constant(uint256) = 10**6  # 1e-12, still needs to be above 0
MAX_FEE: constant(uint256) = 10**17  # 10%
WAD: constant(uint256) = c.WAD

# Implementations which can be changed by governance
amm_blueprint: public(address)
controller_blueprint: public(address)
# convert to blueprint
vault_blueprint: public(address)
controller_view_blueprint: public(address)
ownership_proxy_blueprint: public(address)
    # @notice Blueprint for deploying ownership proxies that enable delegated governance
    # @dev Ownership proxies are created for each market to allow delegation of risk parameters
    # and critical admin functions to trusted entities (see https://github.com/curvefi/ownership-proxy)

fee_receiver: public(address)
emergency: public(address)
    # @notice Emergency admin address with fast-track capabilities for critical actions
    # @dev Used to quickly pause pools or modify critical parameters during protocol emergencies
    # without waiting for full DAO governance. Passed to each ownership proxy on creation.

# Vaults can only be created but not removed
_vaults: IVault[10**18]
# https://github.com/vyperlang/vyper/issues/4721
@external
@view
def vaults(_index: uint256) -> IVault:
    """
    @notice Address of the vault by its index
    """
    return self._vaults[_index]


_vaults_index: HashMap[IVault, uint256]
market_count: public(uint256)

# Checks if a contract (vault, controller or amm) has been deployed by this factory
check_contract: public(HashMap[address, bool])

names: public(HashMap[uint256, String[64]])


@deploy
def __init__(
    _amm_blueprint: address,
    _controller_blueprint: address,
    _vault_blueprint: address,
    _controller_view_blueprint: address,
    _ownership_proxy_blueprint: address,
    _admin: address,
    _emergency: address,
    _fee_receiver: address,
):
    """
    @notice Factory which creates one-way lending vaults (e.g. collateral is non-borrowable)
    @dev Automatically deploys ownership proxies alongside markets to enable delegated governance
    @param _amm_blueprint Address of AMM implementation blueprint
    @param _controller_blueprint Address of Controller implementation blueprint
    @param _vault_blueprint Address of Vault implementation blueprint
    @param _controller_view_blueprint Address of ControllerView implementation blueprint
    @param _ownership_proxy_blueprint Address of OwnershipProxy implementation blueprint
    @param _admin Admin address (DAO) with full governance rights
    @param _emergency Emergency admin address with fast-track permissions for critical actions
    @param _fee_receiver Receiver of interest and admin fees
    """
    self.amm_blueprint = _amm_blueprint
    self.controller_blueprint = _controller_blueprint
    self.vault_blueprint = _vault_blueprint
    self.controller_view_blueprint = _controller_view_blueprint
    self.ownership_proxy_blueprint = _ownership_proxy_blueprint

    ownable.__init__()
    ownable._transfer_ownership(_admin)

    self.fee_receiver = _fee_receiver
    self.emergency = _emergency


@external
def create(
    _borrowed_token: IERC20,
    _collateral_token: IERC20,
    _A: uint256,
    _fee: uint256,
    _loan_discount: uint256,
    _liquidation_discount: uint256,
    _price_oracle: IPriceOracle,
    _monetary_policy: IMonetaryPolicy,
    _name: String[64],
    _supply_limit: uint256,
) -> address[4]:
    """
    @notice Creation of the vault using user-supplied price oracle contract
    @dev Automatically creates and deploys vault, AMM, controller, and ownership proxy for risk delegation
    @param _borrowed_token Token which is being borrowed
    @param _collateral_token Token used for collateral
    @param _A Amplification coefficient: band size is ~1//A
    @param _fee Fee for swaps in AMM (for ETH markets found to be 0.6%)
    @param _loan_discount Maximum discount. LTV = sqrt(((A - 1) // A) ** 4) - loan_discount
    @param _liquidation_discount Liquidation discount. LT = sqrt(((A - 1) // A) ** 4) - liquidation_discount
    @param _price_oracle Custom price oracle contract
    @param _monetary_policy Monetary policy governing borrow rates
    @param _name Human-readable market name
    @param _supply_limit Supply cap for the borrowed token
    @return [0] vault: The lending vault contract
    @return [1] controller: The lending controller managing the market
    @return [2] amm: The AMM contract for swaps and liquidations
    @return [3] ownership_proxy: The ownership proxy enabling delegated governance of risk parameters
    """
    assert _borrowed_token != _collateral_token, "Same token"
    assert _A >= MIN_A and _A <= MAX_A, "Wrong A"
    assert _fee <= MAX_FEE, "Fee too high"
    assert _fee >= MIN_FEE, "Fee too low"

    A_ratio: uint256 = 10**18 * _A // (_A - 1)

    # Validate price oracle
    p: uint256 = (staticcall _price_oracle.price())
    assert p > 0
    assert extcall _price_oracle.price_w() == p

    vault: IVault = IVault(create_from_blueprint(self.vault_blueprint))
    amm: IAMM = IAMM(
        create_from_blueprint(
            self.amm_blueprint,
            _borrowed_token,
            10**convert(18 - staticcall _borrowed_token.decimals(), uint256),
            _collateral_token,
            10**convert(18 - staticcall _collateral_token.decimals(), uint256),
            _A,
            isqrt(A_ratio * 10**18),
            math._wad_ln(convert(A_ratio, int256)),
            p,
            _fee,
            convert(0, uint256),
            _price_oracle,
            code_offset=3,
        )
    )
    controller: IController = IController(
        create_from_blueprint(
            self.controller_blueprint,
            vault,
            amm,
            _borrowed_token,
            _collateral_token,
            _monetary_policy,
            _loan_discount,
            _liquidation_discount,
            self.controller_view_blueprint,
            code_offset=3,
        )
    )
    self.check_contract[vault.address] = True
    self.check_contract[amm.address] = True
    self.check_contract[controller.address] = True

    extcall amm.set_admin(controller.address)

    extcall vault.initialize(amm, controller, _borrowed_token, _collateral_token)

    # Validate monetary policy using controller context
    extcall _monetary_policy.rate_write(controller.address)

    market_count: uint256 = self.market_count
    log ILendFactory.NewVault(
        id=market_count,
        collateral_token=_collateral_token,
        borrowed_token=_borrowed_token,
        vault=vault,
        controller=controller,
        amm=amm,
        price_oracle=_price_oracle,
        monetary_policy=_monetary_policy,
    )
    self._vaults[market_count] = vault
    # Store index with 2**128 offset so missing vault lookups revert (e.g. nonexistent vault would otherwise read index 0)
    self._vaults_index[vault] = market_count + 2**128
    self.names[market_count] = _name
    self.market_count = market_count + 1

    if _supply_limit < max_value(uint256):
        extcall vault.set_max_supply(_supply_limit)

    # Deploy ownership proxy to enable delegated risk parameter governance
    # The proxy receives:
    # - controller.address: ownership admin with full governance rights
    # - ownable.owner: parameter admin with parameter-tuning authority
    # - self.emergency: emergency admin for fast-track critical actions (pause pools, stop A ramps, etc.)
    ownership_proxy: address = create_from_blueprint(
        self.ownership_proxy_blueprint,
        controller.address,
        ownable.owner,
        self.emergency
    )

    return [vault.address, controller.address, amm.address, ownership_proxy]


@external
@view
@reentrant
def markets(_n: uint256) -> ILendFactory.Market:
    vault: IVault = self._vaults[_n]
    controller: IController = staticcall vault.controller()
    amm: IAMM = staticcall vault.amm()

    return ILendFactory.Market(
        vault=vault,
        controller=controller,
        amm=amm,
        collateral_token=staticcall vault.collateral_token(),
        borrowed_token=staticcall vault.borrowed_token(),
        price_oracle=staticcall amm.price_oracle_contract(),
        monetary_policy=staticcall controller.monetary_policy(),
    )


@external
@view
@reentrant
def vaults_index(_vault: IVault) -> uint256:
    return self._vaults_index[_vault] - 2**128


@external
def set_implementations(
    _controller_blueprint: address,
    _amm_blueprint: address,
    _vault_blueprint: address,
    _controller_view_blueprint: address,
    _ownership_proxy_blueprint: address,
):
    """
    @notice Set new implementations (blueprints) for core contracts and ownership proxy
    @dev Only callable by factory admin (DAO). Doesn't change existing markets, only affects new ones.
         Governance can upgrade implementations without affecting deployed instances.
    @param _controller_blueprint Address of the updated controller blueprint
    @param _amm_blueprint Address of the updated AMM blueprint
    @param _vault_blueprint Address of the updated Vault blueprint
    @param _controller_view_blueprint Address of the updated ControllerView blueprint
    @param _ownership_proxy_blueprint Address of the updated OwnershipProxy blueprint
    """
    ownable._check_owner()

    if _controller_blueprint != empty(address):
        self.controller_blueprint = _controller_blueprint
    if _amm_blueprint != empty(address):
        self.amm_blueprint = _amm_blueprint
    if _vault_blueprint != empty(address):
        self.vault_blueprint = _vault_blueprint
    if _controller_view_blueprint != empty(address):
        self.controller_view_blueprint = _controller_view_blueprint
    if _ownership_proxy_blueprint != empty(address):
        self.ownership_proxy_blueprint = _ownership_proxy_blueprint

    log ILendFactory.SetBlueprints(
        amm=_amm_blueprint,
        controller=_controller_blueprint,
        vault=_vault_blueprint,
        controller_view=_controller_view_blueprint,
        ownership_proxy=_ownership_proxy_blueprint,
    )


@external
@view
@reentrant
def admin() -> address:
    """
    @notice Get the admin of the factory
    """
    return ownable.owner


@external
def set_fee_receiver(_fee_receiver: address):
    """
    @notice Set fee receiver who earns interest (DAO)
    @param _fee_receiver Address of the receiver
    """
    ownable._check_owner()
    assert _fee_receiver != empty(address)
    self.fee_receiver = _fee_receiver
    log ILendFactory.SetFeeReceiver(fee_receiver=_fee_receiver)


@external
@view
@reentrant
def coins(_vault_id: uint256) -> IERC20[2]:
    vault: IVault = self._vaults[_vault_id]
    return [staticcall vault.borrowed_token(), staticcall vault.collateral_token()]
