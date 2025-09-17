# pragma version 0.4.3
# pragma nonreentrancy on
# pragma optimize codesize
"""
@title LlamaLend Controller
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2025 - all rights reserved
@notice Main contract to interact with a Llamalend lend market. Each
    contract is specific to a single mint market.
@custom:security security@curve.fi
"""

from contracts.interfaces import IERC20
from contracts.interfaces import IAMM
from contracts.interfaces import IMonetaryPolicy
from contracts.interfaces import IVault

from contracts.interfaces import IMintController as IController

implements: IController

from contracts.interfaces import ILlamalendController

implements: ILlamalendController

from contracts import Controller as core

initializes: core

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


# cumulative amount of assets ever lent
lent: public(uint256)
# cumulative amount of assets collected by admin
collected: public(uint256)


# Unlike mint markets admin fee here is can be less than 100%
admin_fee: public(uint256)
# TODO check this
MAX_ADMIN_FEE: constant(uint256) = 2 * 10**17  # 20%

# TODO add natrix


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
    @notice Controller constructor deployed by the factory from blueprint
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

    core.borrow_cap = 0
    assert extcall core.BORROWED_TOKEN.approve(
        VAULT.address, max_value(uint256), default_return_value=True
    )


@external
@view
def version() -> String[10]:
    return concat(core.version, "-lend")


@external
@view
def borrow_cap() -> uint256:
    """
    @notice Current borrow cap
    """
    return core.borrow_cap


@external
@view
def vault() -> IVault:
    """
    @notice Address of the vault
    """
    return VAULT


@internal
@view
def _borrowed_balance() -> uint256:
    # (VAULT.deposited() - VAULT.withdrawn()) - (self.lent - self.repaid) - self.collected
    return (
        staticcall VAULT.deposited()
        + core.repaid
        - staticcall VAULT.withdrawn()
        - self.lent
        - self.collected
    )


@external
@view
def borrowed_balance() -> uint256:
    return self._borrowed_balance()


# TODO delete deprecated and legacy files

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
    @notice Create loan but pass borrowed to a callback first so that it can build leverage
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
    return core._admin_fees(self.admin_fee)


@external
def collect_fees() -> uint256:
    fees: uint256 = core._collect_fees(self.admin_fee)
    self.collected += fees
    return fees


@internal
def _set_borrow_cap(_borrow_cap: uint256):
    core.borrow_cap = _borrow_cap
    log ILlamalendController.SetBorrowCap(borrow_cap=_borrow_cap)


@external
def set_borrow_cap(_borrow_cap: uint256):
    """
    @notice Set the borrow cap for this market
    @dev Only callable by the factory admin
    @param _borrow_cap New borrow cap in units of borrowed_token
    """
    core._check_admin()
    self._set_borrow_cap(_borrow_cap)


@external
def set_admin_fee(admin_fee: uint256):
    """
    @param admin_fee The fee which should be no higher than MAX_ADMIN_FEE
    """
    core._check_admin()
    assert (
        admin_fee <= MAX_ADMIN_FEE
    )  # dev: admin_fee is higher than MAX_ADMIN_FEE
    self.admin_fee = admin_fee
