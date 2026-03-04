# pragma version 0.4.3
# pragma nonreentrancy on
"""
@title LlamaLend Factory
@notice Factory for one-way lending markets powered by LlamaLend AMM
@author Curve.fi
@license Copyright (c) Curve.Fi, 2020-2025 - all rights reserved
@custom:security security@curve.fi
@custom:kill Pause factory to halt deployments.
"""

from curve_std.interfaces import IERC20

from curve_stablecoin.interfaces import IVault
from curve_stablecoin.interfaces import IController
from curve_stablecoin.interfaces import IAMM
from curve_stablecoin.interfaces import IPriceOracle
from curve_stablecoin.interfaces import ILendFactory
from curve_stablecoin.interfaces import IMonetaryPolicy

implements: ILendFactory

from snekmate.utils import math
from snekmate.utils import pausable
from snekmate.auth import ownable

initializes: ownable
initializes: pausable

from curve_std.utils import role_bindings

initializes: role_bindings

from curve_stablecoin.lending import blueprint_registry

initializes: blueprint_registry

from curve_stablecoin import constants as c


exports: (
    # `owner` is not exported as we refer to it as `admin` for backwards compatibility
    # `renounce_ownership` is intentionally not exported
    pausable.paused,
)


MIN_A: constant(uint256) = 2
MAX_A: constant(uint256) = 10000
MIN_FEE: constant(uint256) = 10**6  # 1e-12, still needs to be above 0
MAX_FEE: constant(uint256) = 10**17  # 10%
WAD: constant(uint256) = c.WAD

ADMIN_ROLE: constant(uint256) = 0
FEE_RECEIVER_ROLE: constant(uint256) = 1

_vaults: IVault[10**18]
_vaults_index: HashMap[IVault, uint256]
market_count: public(uint256)

# Maps contract addresses to market index and type for reverse lookup
check_contract: public(HashMap[address, ILendFactory.ContractInfo])


@deploy
def __init__(
    _amm_blueprint: address,
    _controller_blueprint: address,
    _vault_blueprint: address,
    _controller_view_blueprint: address,
    _admin: address,
    _fee_receiver: address,
):
    """
    @notice Factory which creates one-way lending vaults (e.g. collateral is non-borrowable)
    @param amm Address of AMM implementation
    @param controller Address of Controller implementation
    @param pool_price_oracle Address of implementation for price oracle factory (prices from pools)
    @param admin Admin address (DAO)
    @param fee_receiver Receiver of interest and admin fees
    """
    blueprint_registry.__init__([
        "AMM",  # AMM Blueprint
        "CTR",  # Controller Blueprint
        "VLT",  # Vault Blueprint
        "CTRV", # Controller View Blueprint
    ])
    # This is the only place where we set these blueprints
    blueprint_registry.set("AMM", _amm_blueprint)
    blueprint_registry.set("CTR", _controller_blueprint)
    blueprint_registry.set("VLT", _vault_blueprint)
    blueprint_registry.set("CTRV", _controller_view_blueprint)

    ownable.__init__()
    pausable.__init__()
    ownable._transfer_ownership(_admin)
    role_bindings._init_role(ADMIN_ROLE, _admin)
    role_bindings._init_role(FEE_RECEIVER_ROLE, _fee_receiver)

#    self._set_default_fee_receiver(_fee_receiver)  TODO


@external
@view
def version() -> String[5]:
    return c.__version__


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
) -> address[3]:
    """
    @notice Creation of the vault using user-supplied price oracle contract
    @param _borrowed_token Token which is being borrowed
    @param _collateral_token Token used for collateral
    @param _A Amplification coefficient: band size is ~1//A
    @param _fee Fee for swaps in AMM (for ETH markets found to be 0.6%)
    @param _loan_discount Maximum discount. LTV = sqrt(((A - 1) // A) ** 4) - loan_discount
    @param _liquidation_discount Liquidation discount. LT = sqrt(((A - 1) // A) ** 4) - liquidation_discount
    @param _price_oracle Custom price oracle contract
    @param _name Human-readable market name
    @param _supply_limit Supply cap
    """
    pausable._require_not_paused()
    assert _borrowed_token != _collateral_token, "Same token"
    assert _A >= MIN_A and _A <= MAX_A, "Wrong A"
    assert _fee <= MAX_FEE, "Fee too high"
    assert _fee >= MIN_FEE, "Fee too low"

    A_ratio: uint256 = 10**18 * _A // (_A - 1)

    # Validate price oracle
    p: uint256 = (staticcall _price_oracle.price())
    assert p > 0  # dev: price oracle returned zero
    assert extcall _price_oracle.price_w() == p  # dev: price oracle price() and price_w() mismatch

    vault: IVault = IVault(create_from_blueprint(blueprint_registry.get("VLT")))
    amm: IAMM = IAMM(
        create_from_blueprint(
            blueprint_registry.get("AMM"),
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
        )
    )
    controller: IController = IController(
        create_from_blueprint(
            blueprint_registry.get("CTR"),
            vault,
            amm,
            _borrowed_token,
            _collateral_token,
            _monetary_policy,
            _loan_discount,
            _liquidation_discount,
            blueprint_registry.get("CTRV"),
        )
    )
    market_count: uint256 = self.market_count
    self.check_contract[vault.address] = ILendFactory.ContractInfo(
        market_index=market_count,
        contract_type=ILendFactory.ContractType.VAULT,
    )
    self.check_contract[controller.address] = ILendFactory.ContractInfo(
        market_index=market_count,
        contract_type=ILendFactory.ContractType.CONTROLLER,
    )
    self.check_contract[amm.address] = ILendFactory.ContractInfo(
        market_index=market_count,
        contract_type=ILendFactory.ContractType.AMM,
    )

    extcall amm.set_admin(controller.address)

    extcall vault.initialize(amm, controller, _borrowed_token, _collateral_token)

    # Validate monetary policy using controller context
    extcall _monetary_policy.rate_write(controller.address)
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
    self.market_count = market_count + 1

    if _supply_limit < max_value(uint256):
        extcall vault.set_max_supply(_supply_limit)

    return [vault.address, controller.address, amm.address]


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
@view
def amm_blueprint() -> address:
    """
    @notice Get the address of the AMM blueprint
    """
    return blueprint_registry.get("AMM")


@external
@view
def controller_blueprint() -> address:
    """
    @notice Get the address of the controller blueprint
    """
    return blueprint_registry.get("CTR")


@external
@view
def vault_blueprint() -> address:
    """
    @notice Get the address of the vault blueprint
    """
    return blueprint_registry.get("VLT")


@external
@view
def controller_view_blueprint() -> address:
    """
    @notice Get the address of the controller view blueprint
    """
    return blueprint_registry.get("CTRV")



@external
def set_admin_group(_market: address, _group_id: uint256):
    """
    @notice Assign a _market to an admin group.
    @param _market Market address.
    @param _group_id Custom admin group.
    """
    ownable._check_owner()
    role_bindings._bind_subject_to_group(ADMIN_ROLE, _market, _group_id)


@external
def add_new_admin_group(_admin: address) -> uint256:
    """
    @notice Create a new admin group.
    @param _admin Address for the new group admin.
    @return group_id The id assigned to the new group.
    """
    ownable._check_owner()
    return role_bindings._add_role_group(ADMIN_ROLE, _admin)


@external
def replace_group_admin(_group_id: uint256, _new_admin: address):
    """
    @notice Replace the admin address for a group.
    @param _group_id Admin group id.
    @param _new_admin New admin address.
    """
    ownable._check_owner()
    role_bindings._set_group_assignee(ADMIN_ROLE, _group_id, _new_admin)

@external
def transfer_ownership(_new_owner: address):
    """
    @dev Transfers the ownership of the contract
         to a new account `new_owner`.
    @notice Note that this function can only be
            called by the current `owner`. Also,
            the `new_owner` cannot be the zero address.
    @param _new_owner The 20-byte address of the new owner.
    """
    ownable._check_owner()
    assert _new_owner != empty(address), "ownable: new owner is the zero address"
    ownable._transfer_ownership(_new_owner)
    role_bindings._set_group_assignee(ADMIN_ROLE, 0, _new_owner)


@external
@view
def admin(_contract: address = msg.sender) -> address:
    # Use for Controller and Vault
    return role_bindings._resolve_assignee_of(ADMIN_ROLE, _contract)


@external
def pause():
    """
    @notice Pause new market creation
    """
    ownable._check_owner()
    pausable._pause()


@external
def unpause():
    """
    @notice Unpause the factory to allow new market creation
    """
    ownable._check_owner()
    pausable._unpause()


@external
def set_fee_receiver(_controller: address, _group_id: uint256):
    """
    @notice Assign a _controller to fee_receiver group.
    @param _controller Controller address.
    @param _group_id Custom admin group.
    """
    ownable._check_owner()
    role_bindings._bind_subject_to_group(FEE_RECEIVER_ROLE, _controller, _group_id)


@external
def add_new_fee_receiver_group(_fee_receiver: address) -> uint256:
    """
    @notice Create a new fee receiver group.
    @param _fee_receiver Address for the new group fee receiver.
    @return group_id The id assigned to the new group.
    """
    ownable._check_owner()
    return role_bindings._add_role_group(FEE_RECEIVER_ROLE, _fee_receiver)


@external
def replace_group_fee_receiver(_group_id: uint256, _new_fee_receiver: address):
    """
    @notice Replace the fee receiver address for a group.
    @param _group_id Fee receiver group id.
    @param _new_fee_receiver New fee receiver.
    """
    ownable._check_owner()
    role_bindings._set_group_assignee(FEE_RECEIVER_ROLE, _group_id, _new_fee_receiver)

@external
@view
def default_fee_receiver() -> address:
    return role_bindings._default_assignee(FEE_RECEIVER_ROLE)


@external
@view
def fee_receiver(_controller: address = msg.sender) -> address:
    """
    @notice Get fee receiver who earns interest from admin fees
    @dev This function is called by controllers without specifying the
    first argument to get their fee receiver.
    @param _controller Address of the controller
    """
    return role_bindings._resolve_assignee_of(FEE_RECEIVER_ROLE, _controller)


#@external
#@reentrant
#def set_custom_fee_receiver(_controller: address, _fee_receiver: address):
#    """
#    @notice Set fee receiver who earns admin fees for a specific controller
#    @dev Setting to zero address resets to default fee receiver
#    @param _controller Address of the controller
#    @param _fee_receiver Address of the receiver
#    """
#    ownable._check_owner()
#    contract_info: ILendFactory.ContractInfo = self.check_contract[_controller]
#    assert contract_info.contract_type == ILendFactory.ContractType.CONTROLLER, "not a controller"
#    self.fee_receivers[_controller] = _fee_receiver
#    log ILendFactory.CustomSetFeeReceiver(controller=_controller, fee_receiver=_fee_receiver)


@internal
def _set_default_fee_receiver(_fee_receiver: address):
    role_bindings._set_group_assignee(FEE_RECEIVER_ROLE, 0, _fee_receiver)
    log ILendFactory.SetFeeReceiver(fee_receiver=_fee_receiver)  # Left for consistency


@external
@reentrant
def set_default_fee_receiver(_fee_receiver: address):
    """
    @notice Set default fee receiver who earns admin fees on
    all controllers without a custom fee receiver
    @param _fee_receiver Address of the receiver
    """
    ownable._check_owner()
    self._set_default_fee_receiver(_fee_receiver)


@external
@view
@reentrant
def coins(_vault_id: uint256) -> IERC20[2]:
    vault: IVault = self._vaults[_vault_id]
    return [staticcall vault.borrowed_token(), staticcall vault.collateral_token()]
