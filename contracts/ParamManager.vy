from contracts.interfaces import ILlamalendController
from contracts.interfaces import IAMM
from contracts.interfaces import IPriceOracle
from contracts.interfaces import IMintController as IController
from contracts.interfaces import ILMGauge
from contracts.interfaces import IFactory

from contracts import constants as c


AMM: immutable(IAMM)
# TODO figure out how to differentiate controllers
CONTROLLER: immutable(IController)
FACTORY: immutable(IFactory)
MIN_AMM_FEE: constant(uint256) = 10**6  # 1e-12, still needs to be above 0
MAX_ORACLE_PRICE_DEVIATION: constant(uint256) = c.WAD // 2 # 50% deviation
MAX_AMM_FEE: immutable(uint256)
# TODO getters


@deploy
def __init__(amm: IAMM, controller: IController, factory: IFactory):
    AMM = amm
    CONTROLLER = controller
    FACTORY = factory
    MAX_AMM_FEE = min(c.WAD * c.MIN_TICKS_UINT // staticcall AMM.A(), 10**17)

#########
# UTILS #
#########

@internal
@view
def _check_admin():
    assert msg.sender == staticcall FACTORY.admin(), "only admin"


@internal
def _set_rate(rate: uint256):
    extcall AMM.set_params(
        rate,
        max_value(uint256),
        empty(ILMGauge),
        empty(IPriceOracle)
    )


@internal
def _set_amm_fee(fee: uint256):
    extcall AMM.set_params(
        max_value(uint256), 
        fee,
        empty(ILMGauge),
        empty(IPriceOracle)
    )


# TODO rename ILMGauge to ILMCallback
@internal
def _set_lm_callback(lm_gauge: ILMGauge):
    extcall AMM.set_params(
        max_value(uint256),
        max_value(uint256),
        lm_gauge,
        empty(IPriceOracle)
    )


@internal
def _set_price_oracle(price_oracle: IPriceOracle):
    extcall AMM.set_params(
        max_value(uint256),
        max_value(uint256),
        empty(ILMGauge),
        price_oracle
    )

#######
# AMM #
#######

@external
# @reentrant
def set_amm_fee(fee: uint256):
    """
    @notice Set the AMM fee (factory admin only)
    @dev Reentrant because AMM is nonreentrant TODO check this one
    @param fee The fee which should be no higher than MAX_AMM_FEE
    """
    self._check_admin()
    assert fee <= MAX_AMM_FEE and fee >= MIN_AMM_FEE, "Fee"
    self._set_amm_fee(fee)


@external
def set_callback(cb: ILMGauge):
    """
    @notice Set liquidity mining callback
    """
    self._check_admin()
    self._set_lm_callback(cb)
    log IController.SetLMCallback(callback=cb)


@external
def set_price_oracle(price_oracle: IPriceOracle, max_deviation: uint256):
    """
    @notice Set a new price oracle for the AMM
    @param price_oracle New price oracle contract
    @param max_deviation Maximum allowed deviation for the new oracle
        Can be set to max_value(uint256) to skip the check if oracle is broken.
    """
    self._check_admin()
    # TODO maybe just remove the constant
    assert max_deviation <= MAX_ORACLE_PRICE_DEVIATION or max_deviation == max_value(uint256) # dev: invalid max deviation
    
    # Validate the new oracle has required methods
    extcall price_oracle.price_w()
    new_price: uint256 = staticcall price_oracle.price()
    
    # Check price deviation isn't too high
    current_oracle: IPriceOracle = staticcall AMM.price_oracle_contract()
    old_price: uint256 = staticcall current_oracle.price()
    if max_deviation != max_value(uint256):
        delta: uint256 = new_price - old_price if old_price < new_price else old_price - new_price
        max_delta: uint256 = old_price * max_deviation // c.WAD
        assert delta <= max_delta, "deviation>max"
    
    self._set_price_oracle(price_oracle)

##############
# CONTROLLER #
##############