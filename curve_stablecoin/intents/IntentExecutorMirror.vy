# pragma version 0.4.3
# pragma optimize codesize

"""
@title LlamaLend Intents — Mirror Executor
@author Curve.Finance
@license Copyright (c) Curve.Finance, 2020-2026 - all rights reserved
@notice Deployable executor exposing the 1:1 controller-shaped intent API
        (create_loan / borrow_more / add_collateral / remove_collateral /
        repay / liquidate). Zero semantic gap to IController — intended for
        integrators and differential testing against direct controller calls.
@custom:security security@curve.finance
"""

from curve_stablecoin.intents import intent_lib as lib
from curve_stablecoin.intents import executor_core as core

initializes: lib
initializes: core[lib := lib]

exports: (
    core.create_loan,
    core.borrow_more,
    core.add_collateral,
    core.remove_collateral,
    core.repay,
    core.liquidate,
    core.cancel,
    core.intent_filled,
    core.is_cancelled,
    core.set_paused,
    core.admin,
    core.paused,
)


@deploy
def __init__(_admin: address):
    core.__init__(_admin)
