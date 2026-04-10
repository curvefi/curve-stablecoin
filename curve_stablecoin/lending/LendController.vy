# pragma version 0.4.3
# pragma nonreentrancy on
# pragma optimize codesize
"""
@title LlamaLend Lend Market Controller
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2025 - all rights reserved
@notice Main contract to interact with a Llamalend Lend Market. Each
    contract is specific to a single lending market.
@custom:security security@curve.fi
@custom:kill Set borrow_cap to 0 and vault's max_supply to 0 to prevent new deposits. Existing loans can still be repaid/liquidated.
"""

from curve_std.interfaces import IERC20
from curve_stablecoin.interfaces import IAMM
from curve_stablecoin.interfaces import IMonetaryPolicy
from curve_stablecoin.interfaces import IVault
from curve_stablecoin.interfaces import IController
from curve_std import crv_math

implements: IController

from curve_stablecoin.interfaces import ILendController

implements: ILendController

from curve_stablecoin import controller as core

from curve_stablecoin.interfaces import IControllerView as IView

implements: IView

implements: core.VirtualMethods

initializes: core

from curve_std import token as tkn

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
    core.create_loan_health_preview,
    core.add_collateral_health_preview,
    core.remove_collateral_health_preview,
    core.borrow_more_health_preview,
    core.repay_health_preview,
    core.liquidate_health_preview,
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
    core.view_impl,
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
)

borrow_cap: public(uint256)
VAULT: immutable(IVault)

_available_balance: uint256

@external
@view
def available_balance() -> uint256:
    return self._available_balance


# https://github.com/vyperlang/vyper/issues/4721
@external
@view
@reentrant
def vault() -> address:
    """
    @notice Address of the vault
    """
    return VAULT.address


@deploy
def __init__(
    _vault: IVault,
    _amm: IAMM,
    _borrowed_token: IERC20,
    _collateral_token: IERC20,
    _monetary_policy: IMonetaryPolicy,
    _loan_discount: uint256,
    _liquidation_discount: uint256,
    _view_impl: address,
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
    VAULT = _vault

    core.__init__(
        _collateral_token,
        _borrowed_token,
        _monetary_policy,
        _loan_discount,
        _liquidation_discount,
        _amm,
        _view_impl,
    )

    # Borrow cap is zero by default in lend markets. The admin has to raise it
    # after deployment to allow borrowing.
    core.admin_percentage = 0

    # Pre-approve the vault to transfer borrowed tokens out of the controller
    tkn.max_approve(core.BORROWED_TOKEN, VAULT.address)


@external
@view
@reentrant
def version() -> String[10]:
    """
    @notice Version of this controller
    """
    return concat(core.version, "-lend")


@external
def set_borrow_cap(_borrow_cap: uint256):
    """
    @notice Set the borrow cap for this market
    @dev Only callable by the factory admin
    @param _borrow_cap New borrow cap in units of borrowed_token
    """
    core._check_admin()
    self.borrow_cap = _borrow_cap
    log ILendController.SetBorrowCap(borrow_cap=_borrow_cap)


@external
def set_admin_percentage(_admin_percentage: uint256):
    """
    @param _admin_percentage The percentage of interest that goes to the admin, scaled by 1e18
    """
    core._check_admin()
    assert _admin_percentage <= core.WAD # dev: admin percentage higher than 100%

    # Settle admin fees before the new percentage is applied
    rate_mul: uint256 = staticcall core.AMM.get_rate_mul()
    core._update_total_debt(0, rate_mul, False)

    core.admin_percentage = _admin_percentage
    log ILendController.SetAdminPercentage(admin_percentage=_admin_percentage)


@external
@reentrant
def on_borrowed_token_transfer_in(_amount: uint256):
    """
    @notice Hook called by
            1. The controller on repay/liquidate
            2. The vault on deposit/mint
    """
    assert msg.sender == VAULT.address or msg.sender == self # dev: vault or controller only
    self._available_balance += _amount


@external
@reentrant
def on_borrowed_token_transfer_out(_amount: uint256):
    """
    @notice Hook called by
            1. The controller on create_loan/borrow_more/collect_fees
            2. The vault on withdraw/redeem
    """
    assert msg.sender == VAULT.address or msg.sender == self # dev: vault or controller only
    # core._admin_fees() == 0 in case of collect_fees()
    assert _amount <= crv_math.sub_or_zero(self._available_balance, core._admin_fees()), "Available balance exceeded"
    self._available_balance -= _amount


@external
@reentrant
def _on_debt_increased(_total_debt: uint256):
    """
    @notice Hook called when debt is increased
    """
    assert msg.sender == self # dev: virtual method protection (controller only)
    assert _total_debt <= self.borrow_cap, "Borrow cap exceeded"


@external
@view
def lent() -> uint256:
    """
    @notice Total amount of borrowed tokens lent out since creation
    @return Total lent amount
    """
    return core.lent


@external
@view
def repaid() -> uint256:
    """
    @notice Total amount of borrowed tokens repaid since creation
    @return Total repaid amount
    """
    return core.repaid


@external
@view
def collected() -> uint256:
    """
    @notice Cumulative amount of borrowed assets ever collected as admin fees
    """
    return core.collected
