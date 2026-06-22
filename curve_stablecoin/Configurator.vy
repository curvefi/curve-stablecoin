# pragma version 0.4.3
# pragma nonreentrancy on
"""
@title LlamaLend Markets Configurator
@author Curve.fi
@license Copyright (c) Curve.Fi, 2020-2026 - all rights reserved
@custom:security security@curve.fi
@custom:kill If the underlying market is killed this contract will also be unable to operate.
"""

from curve_stablecoin.interfaces import IController
from curve_stablecoin.interfaces import IConfigurator
from curve_stablecoin.interfaces import ILendController
from curve_stablecoin.interfaces import IMonetaryPolicy
from curve_stablecoin.interfaces import IPriceOracle
from curve_stablecoin.interfaces import ILMCallback
from curve_stablecoin.interfaces import IAMM
from curve_stablecoin import constants as c

implements: IConfigurator

WAD: constant(uint256) = c.WAD
SKIP_CONFIG_UINT256: constant(uint256) = c.SKIP_CONFIG_UINT256
SKIP_CONFIG_ADDRESS: constant(address) = c.SKIP_CONFIG_ADDRESS
MAX_ORACLE_PRICE_DEVIATION: constant(uint256) = WAD // 2  # 50% deviation

default_admin: public(address)
admins: public(HashMap[IController, address])


@deploy
def __init__(_default_admin: address):
    self.default_admin = _default_admin


@external
def set_custom_admin(_controller: IController, _admin: address):
    """
    @notice Set admin for a specific controller
    @dev Setting to zero address resets to default admin
    @param _controller Address of the controller
    @param _admin Address of the admin
    """
    self._check_admin()
    self.admins[_controller] = _admin
    log IConfigurator.SetCustomAdmin(controller=_controller.address, admin=_admin)


@external
def set_owner(_new_default_admin: address):
    """
    @notice Set the contract owner and default admin
    @dev The contract owner is also the default admin used for configurator access control
    @param _new_default_admin Address of the new owner and default admin
    """
    self._check_admin()
    self.default_admin = _new_default_admin
    log IConfigurator.SetDefaultAdmin(new_default_admin=_new_default_admin)


@internal
def _check_admin():
    assert msg.sender == self.default_admin, "Not admin"


@internal
def _check_authorized(_controller: IController):
    assert (
        msg.sender == self.default_admin or msg.sender == self.admins[_controller]
    ), "Not authorized for this controller"


################################################################
#                         CONTROLLER                           #
################################################################

@external
def set_borrowing_discounts(
    _controller: IController, _loan_discount: uint256, _liquidation_discount: uint256
):
    """
    @notice Set discounts at which we can borrow (defines max LTV) and where bad liquidation starts
    @param _controller Address of the controller to configure
    @param _loan_discount Discount which defines LTV
    @param _liquidation_discount Discount where bad liquidation starts
    """
    self._check_authorized(_controller)
    assert _loan_discount != SKIP_CONFIG_UINT256, "loan discount is sentinel"
    assert _liquidation_discount != SKIP_CONFIG_UINT256, "liquidation discount is sentinel"
    assert _liquidation_discount > 0, "liquidation discount = 0"
    assert _loan_discount < WAD, "loan discount >= 100%"
    assert _loan_discount > _liquidation_discount, "loan discount <= liquidation discount"
    extcall _controller.configure(
        _loan_discount,
        _liquidation_discount,
        IMonetaryPolicy(SKIP_CONFIG_ADDRESS),
        SKIP_CONFIG_ADDRESS,
        SKIP_CONFIG_UINT256,
        IPriceOracle(SKIP_CONFIG_ADDRESS),
        ILMCallback(SKIP_CONFIG_ADDRESS),
    )
    log IConfigurator.SetBorrowingDiscounts(
        controller=_controller.address,
        loan_discount=_loan_discount,
        liquidation_discount=_liquidation_discount,
    )


@external
def set_monetary_policy(_controller: IController, _monetary_policy: IMonetaryPolicy):
    """
    @notice Set monetary policy contract
    @param _controller Address of the controller to configure
    @param _monetary_policy Address of the monetary policy contract
    """
    self._check_authorized(_controller)
    assert _monetary_policy.address != SKIP_CONFIG_ADDRESS, "monetary policy is sentinel"
    extcall _controller.configure(
        SKIP_CONFIG_UINT256,
        SKIP_CONFIG_UINT256,
        _monetary_policy,
        SKIP_CONFIG_ADDRESS,
        SKIP_CONFIG_UINT256,
        IPriceOracle(SKIP_CONFIG_ADDRESS),
        ILMCallback(SKIP_CONFIG_ADDRESS),
    )
    extcall _controller.save_rate()
    log IConfigurator.SetMonetaryPolicy(
        controller=_controller.address, monetary_policy=_monetary_policy.address
    )


@external
def set_view(_controller: IController, _view_blueprint: address):
    """
    @notice Change the contract used to store view functions.
    @dev This function deploys a new view implementation from a blueprint.
    @param _controller Address of the controller to configure
    @param _view_blueprint Address of the blueprint to deploy the new view implementation from.
    """
    self._check_authorized(_controller)
    assert _view_blueprint != empty(address), "view blueprint is empty address"
    assert _view_blueprint != SKIP_CONFIG_ADDRESS, "view blueprint is sentinel"

    extcall _controller.configure(
        SKIP_CONFIG_UINT256,
        SKIP_CONFIG_UINT256,
        IMonetaryPolicy(SKIP_CONFIG_ADDRESS),
        _view_blueprint,
        SKIP_CONFIG_UINT256,
        IPriceOracle(SKIP_CONFIG_ADDRESS),
        ILMCallback(SKIP_CONFIG_ADDRESS),
    )

    log IConfigurator.SetView(controller=_controller.address, view=staticcall _controller.view())


################################################################
#                       LEND CONTROLLER                        #
################################################################

@external
def set_borrow_cap(_controller: ILendController, _borrow_cap: uint256):
    """
    @notice Set the borrow cap for a lending market
    @param _controller Address of the lending controller to configure
    @param _borrow_cap New borrow cap in units of borrowed_token
    """
    self._check_authorized(IController(_controller.address))
    assert _borrow_cap != SKIP_CONFIG_UINT256, "borrow cap is sentinel"
    extcall _controller.configure_lend(_borrow_cap, SKIP_CONFIG_UINT256)
    log IConfigurator.SetBorrowCap(controller=_controller.address, borrow_cap=_borrow_cap)


@external
def set_admin_percentage(_controller: ILendController, _admin_percentage: uint256):
    """
    @notice Set the percentage of interest that goes to the admin
    @param _controller Address of the lending controller to configure
    @param _admin_percentage Percentage scaled by 1e18 (e.g. 1e18 == 100%)
    """
    self._check_authorized(IController(_controller.address))
    assert _admin_percentage != SKIP_CONFIG_UINT256, "admin percentage is sentinel"
    assert _admin_percentage <= WAD, "admin percentage higher than 100%"
    extcall _controller.configure_lend(SKIP_CONFIG_UINT256, _admin_percentage)
    log IConfigurator.SetAdminPercentage(
        controller=_controller.address, admin_percentage=_admin_percentage
    )


# ################################################################
# #                             AMM                              #
# ################################################################

@external
def set_price_oracle(
    _controller: IController, _price_oracle: IPriceOracle, _max_deviation: uint256
):
    """
    @notice Set a new price oracle for the AMM
    @param _controller Address of the controller to configure
    @param _price_oracle New price oracle contract
    @param _max_deviation Maximum allowed deviation for the new oracle
        Can be set to max_value(uint256) to skip the check if oracle is broken.
    """
    self._check_authorized(_controller)
    assert _price_oracle.address != SKIP_CONFIG_ADDRESS, "price oracle is sentinel"
    assert (
        _max_deviation <= MAX_ORACLE_PRICE_DEVIATION or _max_deviation == max_value(uint256)
    )  # dev: invalid max deviation

    # Validate the new oracle has required methods
    extcall _price_oracle.price_w()
    new_price: uint256 = staticcall _price_oracle.price()

    # Check price deviation isn't too high (if not skipped)
    if _max_deviation != max_value(uint256):
        amm: IAMM = staticcall _controller.amm()
        current_oracle: IPriceOracle = staticcall amm.price_oracle_contract()
        old_price: uint256 = staticcall current_oracle.price()
        delta: uint256 = (new_price - old_price if old_price < new_price else old_price - new_price)
        max_delta: uint256 = old_price * _max_deviation // WAD
        assert delta <= max_delta, "delta>max"

    extcall _controller.configure(
        SKIP_CONFIG_UINT256,
        SKIP_CONFIG_UINT256,
        IMonetaryPolicy(SKIP_CONFIG_ADDRESS),
        SKIP_CONFIG_ADDRESS,
        SKIP_CONFIG_UINT256,
        _price_oracle,
        ILMCallback(SKIP_CONFIG_ADDRESS),
    )
    log IConfigurator.SetPriceOracle(
        controller=_controller.address, price_oracle=_price_oracle.address
    )


@external
def set_callback(_controller: IController, _cb: ILMCallback):
    """
    @notice Set liquidity mining callback
    @param _controller Address of the controller to configure
    @param _cb Address of the liquidity mining callback contract, or empty address to remove
    """
    self._check_authorized(_controller)
    assert _cb.address != SKIP_CONFIG_ADDRESS, "callback is sentinel"
    extcall _controller.configure(
        SKIP_CONFIG_UINT256,
        SKIP_CONFIG_UINT256,
        IMonetaryPolicy(SKIP_CONFIG_ADDRESS),
        SKIP_CONFIG_ADDRESS,
        SKIP_CONFIG_UINT256,
        IPriceOracle(SKIP_CONFIG_ADDRESS),
        _cb,
    )
    log IConfigurator.SetCallback(controller=_controller.address, callback=_cb.address)


@external
def set_amm_fee(_controller: IController, _fee: uint256):
    """
    @notice Set the AMM fee
    @param _controller Address of the controller to configure
    @param _fee The fee which should be no higher than MAX_AMM_FEE
    """
    self._check_authorized(_controller)
    assert _fee != SKIP_CONFIG_UINT256, "fee is sentinel"
    extcall _controller.configure(
        SKIP_CONFIG_UINT256,
        SKIP_CONFIG_UINT256,
        IMonetaryPolicy(SKIP_CONFIG_ADDRESS),
        SKIP_CONFIG_ADDRESS,
        _fee,
        IPriceOracle(SKIP_CONFIG_ADDRESS),
        ILMCallback(SKIP_CONFIG_ADDRESS),
    )
    log IConfigurator.SetAmmFee(controller=_controller.address, fee=_fee)
