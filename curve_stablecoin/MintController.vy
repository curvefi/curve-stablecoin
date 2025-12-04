# pragma version 0.4.3
# pragma nonreentrancy on
# pragma optimize codesize
"""
@title Mint Controller
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2025 - all rights reserved
@notice This is just a simple adapter not to have to deploy a new
    factory for mint markets.
@custom:security security@curve.fi
"""

from curve_stablecoin import Controller as core

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
    core.__init__(
        _collateral_token,
        staticcall core.IFactory(msg.sender).stablecoin(),
        _monetary_policy,
        _loan_discount,
        _liquidation_discount,
        _amm,
        empty(address),  # to replace at deployment with view blueprint
    )
