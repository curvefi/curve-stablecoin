# pragma version 0.4.3
# pragma nonreentrancy on

from curve_stablecoin.interfaces import IController
from curve_stablecoin.interfaces import IConfigurator
from curve_stablecoin.interfaces import ILendFactory
from curve_stablecoin.interfaces import ILendController
from curve_stablecoin.interfaces import IMonetaryPolicy
from curve_stablecoin import constants as c

WAD: constant(uint256) = c.WAD
SKIP_CONFIG: constant(uint256) = c.SKIP_CONFIG
SKIP_CONFIG_ADDRESS: constant(address) = c.SKIP_CONFIG_ADDRESS

@internal
def _check_admin():
    # TODO implement in a way where each market can have custom admins (possibly through factory?)
    pass


################################################################
#                         CONTROLLER                           #
################################################################
# TODO rename to LlamalendConfigurator

@external
def set_borrowing_discounts(
    _controller: IController,
    _loan_discount: uint256,
    _liquidation_discount: uint256
):
    """
    @notice Set discounts at which we can borrow (defines max LTV) and where bad liquidation starts
    @param _loan_discount Discount which defines LTV
    @param _liquidation_discount Discount where bad liquidation starts
    """
    self._check_admin()
    assert _liquidation_discount > 0, "liquidation discount = 0"
    assert _loan_discount < WAD, "loan discount >= 100%"
    assert _loan_discount > _liquidation_discount, "loan discount <= liquidation discount"
    extcall _controller.configure(
        _loan_discount,
        _liquidation_discount,
        IMonetaryPolicy(SKIP_CONFIG_ADDRESS),
        SKIP_CONFIG_ADDRESS,
    )
    log IConfigurator.SetBorrowingDiscounts(
        loan_discount=_loan_discount, liquidation_discount=_liquidation_discount
    )


@external
def set_monetary_policy(
    _controller: IController,
    _monetary_policy: IMonetaryPolicy
):
    """
    @notice Set monetary policy contract
    @param _monetary_policy Address of the monetary policy contract
    """
    self._check_admin()
    extcall _controller.configure(
        SKIP_CONFIG,
        SKIP_CONFIG,
        _monetary_policy,
        SKIP_CONFIG_ADDRESS,
    )
    extcall _monetary_policy.rate_write()
    log IConfigurator.SetMonetaryPolicy(monetary_policy=_monetary_policy)


@external
def set_view(
    _controller: IController,
    _view_blueprint: address
):
    """
    @notice Change the contract used to store view functions.
    @dev This function deploys a new view implementation from a blueprint.
    @param _view_blueprint Address of the blueprint to deploy the new view implementation from.
    """
    self._check_admin()
    assert _view_blueprint != empty(address), "view blueprint is empty address"

    extcall _controller.configure(
        SKIP_CONFIG,
        SKIP_CONFIG,
        IMonetaryPolicy(SKIP_CONFIG_ADDRESS),
        _view_blueprint,
    )

    log IConfigurator.SetView(view=staticcall _controller.view())


################################################################
#                       LEND CONTROLLER                        #
################################################################

@external
def set_borrow_cap(_controller: ILendController, _borrow_cap: uint256):
    """
    @notice Set the borrow cap for a lending market
    @param _borrow_cap New borrow cap in units of borrowed_token
    """
    self._check_admin()
    extcall _controller.configure_lend(_borrow_cap, SKIP_CONFIG)
    log IConfigurator.SetBorrowCap(borrow_cap=_borrow_cap)


@external
def set_admin_percentage(_controller: ILendController, _admin_percentage: uint256):
    """
    @notice Set the percentage of interest that goes to the admin
    @param _admin_percentage Percentage scaled by 1e18 (e.g. 1e18 == 100%)
    """
    self._check_admin()
    assert _admin_percentage <= WAD, "admin percentage higher than 100%"
    extcall _controller.configure_lend(SKIP_CONFIG, _admin_percentage)
    log IConfigurator.SetAdminPercentage(admin_percentage=_admin_percentage)





# ################################################################
# #                             AMM                              #
# ################################################################

# # TODO add this to formatter
# @external
# def set_price_oracle(
#     _amm: IAMM,
#     _price_oracle: IPriceOracle, _max_deviation: uint256):
#     """
#     @notice Set a new price oracle for the AMM
#     @param _price_oracle New price oracle contract
#     @param _max_deviation Maximum allowed deviation for the new oracle
#         Can be set to max_value(uint256) to skip the check if oracle is broken.
#     """
#     self._check_admin()
#     assert (
#         _max_deviation <= MAX_ORACLE_PRICE_DEVIATION
#         or _max_deviation == max_value(uint256)
#     )  # dev: invalid max deviation

#     # Validate the new oracle has required methods
#     extcall _price_oracle.price_w()
#     new_price: uint256 = staticcall _price_oracle.price()

#     # Check price deviation isn't too high
#     current_oracle: IPriceOracle = staticcall AMM.price_oracle_contract()
#     old_price: uint256 = staticcall current_oracle.price()
#     if _max_deviation != max_value(uint256):
#         delta: uint256 = (
#             new_price - old_price
#             if old_price < new_price
#             else old_price - new_price
#         )
#         max_delta: uint256 = old_price * _max_deviation // WAD
#         assert delta <= max_delta, "delta>max"

#     self._price_oracle = _price_oracle
#     log IAMM.SetPriceOracle(price_oracle=_price_oracle)


# @external
# def set_callback(
#     _amm: IAMM,
#     _cb: ILMGauge):
#     """
#     @notice Set liquidity mining callback
#     """
#     self._check_admin()
#     self._liquidity_mining_callback = liquidity_mining_callback
#     log IController.SetLMCallback(callback=_cb)


# @external
# def set_amm_fee(
#     _amm: IAMM,
#     _fee: uint256):
#     """
#     @notice Set the AMM fee
#     @param _fee The fee which should be no higher than MAX_AMM_FEE
#     """
#     self._check_admin()
#     assert _fee <= MAX_AMM_FEE and _fee >= MIN_AMM_FEE, "Fee"
#     self.fee = _fee
#     log IAMM.SetFee(fee=_fee)
