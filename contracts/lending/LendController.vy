# pragma version 0.4.3
# pragma nonreentrancy on
# pragma optimize codesize
"""
@title LlamaLend Lend Market Controller
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2025 - all rights reserved
@notice Main contract to interact with a Llamalend Lend Market. Each
    contract is specific to a single mint market.
@custom:security security@curve.fi
"""

from contracts.interfaces import IERC20
from contracts.interfaces import IAMM
from contracts.interfaces import IMonetaryPolicy
from contracts.interfaces import IVault
from contracts.interfaces import IController

implements: IController

from contracts.interfaces import ILlamalendController

implements: ILlamalendController

from contracts import Controller as core

initializes: core

from contracts.lib import token_lib as tkn

exports: (
    # Loan management
    core.add_collateral,
    core.approve,
    core.remove_collateral,
    core.repay,
    core.set_extra_health,
    core.liquidate,
    core.save_rate,
    # Getters
    core.amm,
    core.amm_price,
    core.approval,
    core.borrowed_token,
    core.calculate_debt_n1,
    core.collateral_token,
    core.debt,
    core.extra_health,
    core.health,
    core.health_calculator,
    core.liquidation_discount,
    core.liquidation_discounts,
    core.loan_discount,
    core.loan_exists,
    core.loan_ix,
    core.loans,
    core.monetary_policy,
    core.n_loans,
    core.tokens_to_liquidate,
    core.tokens_to_shrink,
    core.total_debt,
    core.factory,
    core.processed,
    core.repaid,
    # Setters
    core.set_view,
    core.set_amm_fee,
    core.set_borrowing_discounts,
    core.set_callback,
    core.set_monetary_policy,
    core.set_price_oracle,
    # From view contract
    core.user_prices,
    core.user_state,
    core.users_to_liquidate,
    core.min_collateral,
    core.max_borrowable,
    # For compatibility with mint markets ABI
    core.minted,
    core.redeemed,
)

VAULT: immutable(IVault)

# https://github.com/vyperlang/vyper/issues/4721
@external
@view
def vault() -> IVault:
    """
    @notice Address of the vault
    """
    return VAULT



# cumulative amount of assets ever lent
lent: public(uint256)
# cumulative amount of assets collected by admin
collected: public(uint256)

# TODO Rename to admin percentage?
admin_fee: public(uint256)


@deploy
def __init__(
    vault: IVault,
    amm: IAMM,
    borrowed_token: IERC20,
    collateral_token: IERC20,
    monetary_policy: IMonetaryPolicy,
    loan_discount: uint256,
    liquidation_discount: uint256,
    view_impl: address,
):
    """
    @notice Lend Controller constructor
    @param collateral_token Token to use for collateral
    @param monetary_policy Address of monetary policy
    @param loan_discount Discount of the maximum loan size compare to get_x_down() value
    @param liquidation_discount Discount of the maximum loan size compare to
           get_x_down() for "bad liquidation" purposes
    @param amm AMM address (Already deployed from blueprint)
    """
    VAULT = vault

    core.__init__(
        collateral_token,
        borrowed_token,
        monetary_policy,
        loan_discount,
        liquidation_discount,
        amm,
        view_impl,
    )

    # Borrow cap is zero by default in lend markets. The admin has to raise it
    # after deployment to allow borrowing.
    core.borrow_cap = 0

    # Pre-approve the vault to transfer borrowed tokens out of the controller
    tkn.max_approve(core.BORROWED_TOKEN, VAULT.address)


@external
@view
def version() -> String[10]:
    """
    @notice Version of this controller
    """
    return concat(core.version, "-lend")


@external
@view
def borrow_cap() -> uint256:
    """
    @notice Maximum amount of borrowed tokens that can be lent out at any time.
    """
    return core.borrow_cap


@external
@view
def borrowed_balance() -> uint256:
    """
    @notice Amount of borrowed token the controller currently holds.
    @dev Used by the vault for its accounting logic.
    """
    # TODO rename to `borrowed_token_balance` for clarity?
    # Start from the vault’s erc20 balance (ignoring any tokens sent directly to the vault),
    # subtract the portion we actually lent out that hasn’t been repaid yet (lent − repaid),
    # and subtract what the admin already skimmed as fees; what’s left is the controller’s idle cash.
    # VAULT.asset_balance() - (lent - repaid) - self.collected
    # The terms are rearranged to avoid underflows in intermediate steps.
    return (
        staticcall VAULT.asset_balance()
        + core.repaid
        - self.lent
        - self.collected
    )


@external
def create_loan(
    collateral: uint256,
    debt: uint256,
    N: uint256,
    _for: address = msg.sender,
    callbacker: address = empty(address),
    calldata: Bytes[10**4] = b"",
):
    """
    @notice Create loan but pass borrowed tokens to a callback first so that it can build leverage
    @param collateral Amount of collateral to use
    @param debt Borrowed asset debt to take
    @param N Number of bands to deposit into (to do autoliquidation-deliquidation),
           can be from MIN_TICKS to MAX_TICKS
    @param _for Address to create the loan for
    @param callbacker Address of the callback contract
    @param calldata Any data for callbacker
    """
    _debt: uint256 = core._create_loan(
        collateral, debt, N, _for, callbacker, calldata
    )
    self.lent += _debt


@external
def borrow_more(
    collateral: uint256,
    debt: uint256,
    _for: address = msg.sender,
    callbacker: address = empty(address),
    calldata: Bytes[10**4] = b"",
):
    """
    @notice Borrow more borrowed tokens while adding more collateral using a callback (to leverage more)
    @param collateral Amount of collateral to add
    @param debt Amount of borrowed asset debt to take
    @param _for Address to borrow for
    @param callbacker Address of the callback contract
    @param calldata Any data for callbacker
    """
    _debt: uint256 = core._borrow_more(
        collateral,
        debt,
        _for,
        callbacker,
        calldata,
    )

    self.lent += _debt


@external
@view
def admin_fees() -> uint256:
    """
    @notice Return the amount of borrowed tokens that have been collected as fees.
    """
    return core._admin_fees(self.admin_fee)[0]


@external
def collect_fees() -> uint256:
    """
    @notice Collect the fees charged as interest that belong to the admin.
    """
    fees: uint256 = core._collect_fees(self.admin_fee)
    self.collected += fees
    return fees


@external
def set_borrow_cap(_borrow_cap: uint256):
    """
    @notice Set the borrow cap for this market
    @dev Only callable by the factory admin
    @param _borrow_cap New borrow cap in units of borrowed_token
    """
    core._check_admin()
    core.borrow_cap = _borrow_cap
    log ILlamalendController.SetBorrowCap(borrow_cap=_borrow_cap)


@external
def set_admin_fee(_admin_fee: uint256):
    """
    @param _admin_fee The percentage of interest that goes to the admin, scaled by 1e18
    """
    core._check_admin()
    assert _admin_fee <= core.WAD # dev: admin fee higher than 100%
    self.admin_fee = _admin_fee
    log ILlamalendController.SetAdminFee(admin_fee=_admin_fee)
