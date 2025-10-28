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
from contracts.lib import math_lib as crv_math

exports: (
    # Loan management
    core.create_loan,
    core.borrow_more,
    core.add_collateral,
    core.approve,
    core.remove_collateral,
    core.repay,
    core.set_extra_health,
    core.liquidate,
    core.save_rate,
    core.collect_fees,
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
    core.admin_fees,
    core.admin_percentage,
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

borrow_cap: public(uint256)
VAULT: immutable(IVault)


# https://github.com/vyperlang/vyper/issues/4721
@external
@view
def vault() -> address:
    """
    @notice Address of the vault
    """
    return VAULT.address


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
    core.admin_percentage = 0

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
def collected() -> uint256:
    """
    @notice Cumulative amount of borrowed assets ever collected as admin fees
    """
    return core.collected


@internal
@view
def _borrowed_balance() -> uint256:
    # TODO rename to `borrowed_token_balance` for clarity?
    # Start from the vault’s erc20 balance (ignoring any tokens sent directly to the vault),
    # subtract the portion we actually lent out that hasn’t been repaid yet (lent − repaid),
    # and subtract what the admin already skimmed as fees; what’s left is the controller’s idle cash.
    # VAULT.asset_balance() - (lent - repaid) - self.collected
    # The terms are rearranged to avoid underflows in intermediate steps.
    # TODO handle asset_balance() underflow
    balance: uint256 = (staticcall VAULT.asset_balance()
        + core.repaid
        - core.lent
        - core.collected
    )
    return crv_math.sub_or_zero(balance, core.admin_fees)\


@external
@view
def borrowed_balance() -> uint256:
    """
    @notice Amount of borrowed token the controller currently holds.
    @dev Used by the vault for its accounting logic.
    """
    return self._borrowed_balance()


@external
def set_borrow_cap(_borrow_cap: uint256):
    """
    @notice Set the borrow cap for this market
    @dev Only callable by the factory admin
    @param _borrow_cap New borrow cap in units of borrowed_token
    """
    core._check_admin()
    self.borrow_cap = _borrow_cap
    log ILlamalendController.SetBorrowCap(borrow_cap=_borrow_cap)


@external
def set_admin_percentage(_admin_percentage: uint256):
    """
    @param _admin_percentage The percentage of interest that goes to the admin, scaled by 1e18
    """
    core._check_admin()
    assert _admin_percentage <= core.WAD # dev: admin percentage higher than 100%
    core.admin_percentage = _admin_percentage
    log ILlamalendController.SetAdminPercentage(admin_percentage=_admin_percentage)


@external
@reentrant
def _on_debt_increased(debt: uint256):
    """
    @notice Hook called when debt is increased
    """
    assert msg.sender == self # dev: virtual method protection
    assert debt <= self.borrow_cap, "Borrow cap exceeded"
    assert debt <= self._borrowed_balance(), "Borrowed balance exceeded"
