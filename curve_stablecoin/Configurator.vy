# pragma version 0.4.3
# pragma nonreentrancy on

@internal
def _check_admin():
    # TODO implement in a way where each market can have custom admins (possibly through factory?)
    pass

################################################################
#                         CONTROLLER                           #
################################################################

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
    assert _liquidation_discount > 0 # dev: liquidation discount = 0
    assert _loan_discount < WAD # dev: loan discount >= 100%
    assert _loan_discount > _liquidation_discount # dev: loan discount <= liquidation discount
    self.liquidation_discount = _liquidation_discount
    self.loan_discount = _loan_discount
    log IController.SetBorrowingDiscounts(
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
    self._monetary_policy = _monetary_policy
    extcall _monetary_policy.rate_write()
    log IController.SetMonetaryPolicy(monetary_policy=_monetary_policy)


@external
def set_view(
    _controller: IController,
    _view_impl: address
):
    """
    @notice Change the contract used to store view functions.
    @dev This function deploys a new view implementation from a blueprint.
    @param _view_impl Address of the new view implementation
    """
    self._check_admin()
    assert _view_impl != empty(address) # dev: view implementation is empty address
    self.view_impl = _view_impl
    view: address = create_from_blueprint(
        _view_impl,
        self,
        SQRT_BAND_RATIO,
        LOGN_A_RATIO,
        AMM,
        A,
        COLLATERAL_TOKEN,
        COLLATERAL_PRECISION,
        BORROWED_TOKEN,
        BORROWED_PRECISION,
    )
    self._view = IView(view)

    log IController.SetView(view=view)



################################################################
#                             AMM                              #
################################################################

# TODO add this to formatter
@external
def set_price_oracle(
    _amm: IAMM,
    _price_oracle: IPriceOracle, _max_deviation: uint256):
    """
    @notice Set a new price oracle for the AMM
    @param _price_oracle New price oracle contract
    @param _max_deviation Maximum allowed deviation for the new oracle
        Can be set to max_value(uint256) to skip the check if oracle is broken.
    """
    self._check_admin()
    assert (
        _max_deviation <= MAX_ORACLE_PRICE_DEVIATION
        or _max_deviation == max_value(uint256)
    )  # dev: invalid max deviation

    # Validate the new oracle has required methods
    extcall _price_oracle.price_w()
    new_price: uint256 = staticcall _price_oracle.price()

    # Check price deviation isn't too high
    current_oracle: IPriceOracle = staticcall AMM.price_oracle_contract()
    old_price: uint256 = staticcall current_oracle.price()
    if _max_deviation != max_value(uint256):
        delta: uint256 = (
            new_price - old_price
            if old_price < new_price
            else old_price - new_price
        )
        max_delta: uint256 = old_price * _max_deviation // WAD
        assert delta <= max_delta, "delta>max"

    self._price_oracle = _price_oracle
    log IAMM.SetPriceOracle(price_oracle=_price_oracle)


@external
def set_callback(
    _amm: IAMM,
    _cb: ILMGauge):
    """
    @notice Set liquidity mining callback
    """
    self._check_admin()
    self._liquidity_mining_callback = liquidity_mining_callback
    log IController.SetLMCallback(callback=_cb)


@external
def set_amm_fee(
    _amm: IAMM,
    _fee: uint256):
    """
    @notice Set the AMM fee 
    @param _fee The fee which should be no higher than MAX_AMM_FEE
    """
    self._check_admin()
    assert _fee <= MAX_AMM_FEE and _fee >= MIN_AMM_FEE, "Fee"
    self.fee = _fee
    log IAMM.SetFee(fee=_fee)


@external
def set_rate(
    _amm: IAMM
    _rate: uint256) -> uint256:
    """
    @notice Set interest rate. That affects the dependence of AMM base price over time
    @param rate New rate in units of int(fraction * 1e18) per second
    @return rate_mul multiplier (e.g. 1.0 + integral(rate, dt))
    """
    assert msg.sender == self.admin
    rate_mul: uint256 = self._rate_mul()
    self.rate_mul = rate_mul
    self.rate_time = block.timestamp
    self.rate = rate
    log IAMM.SetRate(rate=rate, rate_mul=rate_mul, time=block.timestamp)
    return rate_mul