# pragma version 0.4.3
# pragma nonreentrancy on
# pragma optimize codesize
"""
@title Llamalend V2 Mint Market Controller
@author Curve.Finance
@license Copyright (c) Curve.Finance, 2020-2026 - all rights reserved
@notice Main contract to interact with a Llamalend Mint Market. Each contract is specific to a single mint market.
@dev This is just a simple adapter not to have to deploy a new factory for mint markets.
@custom:security security@curve.finance
@custom:kill Set debt_ceiling to 0 via ControllerFactory to prevent new loans. Existing loans can still be repaid/liquidated.
"""

from curve_stablecoin import controller as core

initializes: core

# Usually a bad practice to expose through
# `__interface__` but this contract is just
# an adapter to make the construct of Controller
# compatible with the old mint factory.
exports: core.__interface__


@deploy
def __init__(
    _collateral_token: core.IERC20,
    _monetary_policy: core.IMonetaryPolicy,
    _loan_discount: uint256,
    _liquidation_discount: uint256,
    _amm: core.IAMM,
):
    """
    @notice Mint Controller constructor
    @param _collateral_token Token used as collateral
    @param _monetary_policy Address of the monetary policy contract
    @param _loan_discount Discount of the maximum loan size compared to get_x_down() value
    @param _liquidation_discount Discount of the maximum loan size compared to
           get_x_down() for "bad liquidation" purposes
    @param _amm AMM address (already deployed from blueprint)
    """
    core.__init__(
        _collateral_token,
        staticcall core.IFactory(msg.sender).stablecoin(),
        _monetary_policy,
        _loan_discount,
        _liquidation_discount,
        _amm,
        empty(address),  # to replace at deployment with view blueprint
        core.IConfigurator(empty(address)),  # to replace at deployment with configurator
    )
