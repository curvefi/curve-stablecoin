# pragma version 0.4.3
# pragma nonreentrancy on
# pragma optimize codesize
"""
@title Mint Controller
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2025 - all rights reserved
@notice This is just a simple adapter not to have to deploy a new
    factory for mint markets.
"""

import Controller as core
initializes: core

# Usually a bad practice to expose through
# `__interface__` but this contract is just
# an adapter for the constructor of the Controller
exports: core.__interface__


@deploy
def __init__(
    collateral_token: core.IERC20,
    monetary_policy: core.IMonetaryPolicy,
    loan_discount: uint256,
    liquidation_discount: uint256,
    amm: core.IAMM,
):
    core.__init__(
        collateral_token,
        staticcall core.IFactory(msg.sender).stablecoin(),
        monetary_policy,
        loan_discount,
        liquidation_discount,
        amm,
        empty(address),  # to replace at deployment with view blueprint
    )

    # TODO do this differently
    assert extcall core.BORROWED_TOKEN.approve(
        core.FACTORY.address, max_value(uint256), default_return_value=True
    )
