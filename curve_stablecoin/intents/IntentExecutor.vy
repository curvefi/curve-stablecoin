# pragma version 0.4.3
# pragma optimize codesize

"""
@title LlamaLend Intents — 2-method Executor (borrow + repay)
@author Curve.Finance
@license Copyright (c) Curve.Finance, 2020-2026 - all rights reserved
@notice User-facing executor: the whole borrower op matrix collapses into
        two EIP-712 intent types split by risk direction.
        Borrow = anything that lowers health / withdraws value
                 (open loan, borrow more, lever up, remove collateral).
        Repay  = anything that raises health or closes
                 (wallet repay, delever from collateral, add collateral,
                  shrink, full close).
        Dispatch onto executor_core's `_do_*` primitives, including
        sequencing multi-call combos under one signed intent.
@dev Fill units: debt units when the intent moves debt, collateral units
     for pure collateral moves. `debt_*` == MAX_UINT means "to full".
@custom:security security@curve.finance
"""

from curve_stablecoin.interfaces import IController

from curve_stablecoin.intents import intent_lib as lib
from curve_stablecoin.intents import executor_core as core

initializes: lib
initializes: core[lib := lib]

exports: (
    core.cancel,
    core.intent_filled,
    core.is_cancelled,
    core.set_paused,
    core.admin,
    core.paused,
)


################################################################
#                          CONSTANTS                           #
################################################################

ROUTE_MAX: constant(uint256) = 4096
MAX_UINT: constant(uint256) = max_value(uint256)

OP_BORROW: constant(uint8) = 21
OP_REPAY: constant(uint8) = 22

BORROW_TYPEHASH: constant(bytes32) = keccak256(
    "BorrowIntent(Common common,uint256 debtAdd,int256 collateralDelta,"
    "uint256 bands,uint256 swapMinOut,int256 minHealthAfter)"
    "Common(address user,address controller,uint256 priceBelow,"
    "uint256 priceAbove,int256 healthBelow,uint256 rateAbove,"
    "uint256 rateBelow,uint256 deadline,uint256 nonce,uint256 minFill,"
    "uint256 cooldown,uint256 feeStartBps,uint256 feeEndBps,uint256 decayStart)"
)
REPAY_TYPEHASH: constant(bytes32) = keccak256(
    "RepayIntent(Common common,uint256 debtSub,uint256 collateralAdd,"
    "bool useCollateral,bool shrink,uint256 swapMinOut,int256 minHealthAfter)"
    "Common(address user,address controller,uint256 priceBelow,"
    "uint256 priceAbove,int256 healthBelow,uint256 rateAbove,"
    "uint256 rateBelow,uint256 deadline,uint256 nonce,uint256 minFill,"
    "uint256 cooldown,uint256 feeStartBps,uint256 feeEndBps,uint256 decayStart)"
)


################################################################
#                           STRUCTS                            #
################################################################

struct BorrowIntent:
    common: lib.Common
    debt_add: uint256        # cumulative cap of new debt; 0 = pure collateral move
    collateral_delta: int256 # >0 pull from wallet (pro-rata), <0 withdraw to wallet
    bands: uint256           # N, used only when the fill opens the loan
    swap_min_out: uint256    # leverage price floor: collateral wei per WAD debt; 0 = plain
    min_health_after: int256

struct RepayIntent:
    common: lib.Common
    debt_sub: uint256        # cumulative cap of debt repaid; MAX_UINT = full close
    collateral_add: uint256  # wallet collateral for the FULL intent (pro-rata); 0 = none
    use_collateral: bool     # repay out of position collateral (delever)
    shrink: bool             # shrink the band range while repaying
    swap_min_out: uint256    # delever price floor: borrowed wei per WAD collateral
    min_health_after: int256

event IntentFill:
    intent_hash: indexed(bytes32)
    user: indexed(address)
    controller: indexed(address)
    op: uint8
    amount: uint256
    fee: uint256
    solver: address


@deploy
def __init__(_admin: address):
    core.__init__(_admin)


################################################################
#                           BORROW                             #
################################################################

@external
@nonreentrant
def borrow(
    intent: BorrowIntent,
    _sig: Bytes[65],
    _amount: uint256,  # fill slice in intent units; MAX_UINT = remaining
    _callbacker: address = empty(address),
    _route: Bytes[ROUTE_MAX] = b"",
):
    """
    @notice Health-decreasing fill: open/extend a loan and/or withdraw
            collateral, optionally levering the minted debt into collateral.
    """
    c: lib.Common = intent.common
    h: bytes32 = lib._digest(
        keccak256(
            abi_encode(
                BORROW_TYPEHASH,
                lib._hash_common(c),
                intent.debt_add,
                intent.collateral_delta,
                intent.bands,
                intent.swap_min_out,
                intent.min_health_after,
            )
        )
    )
    core._pre_fill(c, h)
    lib._verify_sig(c.user, h, _sig)

    ctrl: IController = IController(c.controller)
    cap: uint256 = intent.debt_add
    d: uint256 = 0

    if intent.debt_add > 0:
        d = core._slice(h, cap, _amount)
        # wallet collateral leg, pro-rata to the debt slice
        coll_in: uint256 = 0
        if intent.collateral_delta > 0:
            coll_in = convert(intent.collateral_delta, uint256) * d // intent.debt_add

        if staticcall ctrl.loan_exists(c.user):
            core._do_borrow_more(
                ctrl, c.user, coll_in, d, intent.swap_min_out, _callbacker, _route
            )
        else:
            core._do_create_loan(
                ctrl, c.user, coll_in, d, intent.bands,
                intent.swap_min_out, _callbacker, _route,
            )

        # optional withdraw leg (same risk direction), pro-rata
        if intent.collateral_delta < 0:
            coll_out: uint256 = (
                convert(-intent.collateral_delta, uint256) * d // intent.debt_add
            )
            if coll_out > 0:
                core._do_remove_collateral(ctrl, c.user, coll_out)
    else:
        # pure collateral withdrawal; fill units = collateral
        assert intent.collateral_delta < 0, "empty intent"
        cap = convert(-intent.collateral_delta, uint256)
        d = core._slice(h, cap, _amount)
        core._do_remove_collateral(ctrl, c.user, d)

    lib._register_fill(h, c, cap, d)
    core._post_health(ctrl, c.user, intent.min_health_after)

    fee: uint256 = 0
    if intent.debt_add > 0:
        fee = core._pay_fee(c, staticcall ctrl.borrowed_token(), d, msg.sender)
    else:
        fee = core._pay_fee(c, staticcall ctrl.collateral_token(), d, msg.sender)
    log IntentFill(
        intent_hash=h, user=c.user, controller=c.controller,
        op=OP_BORROW, amount=d, fee=fee, solver=msg.sender,
    )


################################################################
#                            REPAY                             #
################################################################

@external
@nonreentrant
def repay(
    intent: RepayIntent,
    _sig: Bytes[65],
    _amount: uint256,  # fill slice in intent units; MAX_UINT = remaining
    _callbacker: address = empty(address),
    _route: Bytes[ROUTE_MAX] = b"",
):
    """
    @notice Health-increasing fill: repay debt from wallet or position
            collateral, add collateral, shrink, or close the position.
    """
    c: lib.Common = intent.common
    h: bytes32 = lib._digest(
        keccak256(
            abi_encode(
                REPAY_TYPEHASH,
                lib._hash_common(c),
                intent.debt_sub,
                intent.collateral_add,
                intent.use_collateral,
                intent.shrink,
                intent.swap_min_out,
                intent.min_health_after,
            )
        )
    )
    core._pre_fill(c, h)
    lib._verify_sig(c.user, h, _sig)

    ctrl: IController = IController(c.controller)
    cap: uint256 = intent.debt_sub
    actual: uint256 = 0

    if intent.debt_sub > 0:
        # optional collateral top-up leg first (same risk direction)
        if intent.collateral_add > 0 and intent.debt_sub != MAX_UINT:
            d_want: uint256 = core._slice(h, cap, _amount)
            core._do_add_collateral(
                ctrl, c.user, intent.collateral_add * d_want // intent.debt_sub
            )
        elif intent.collateral_add > 0:
            core._do_add_collateral(ctrl, c.user, intent.collateral_add)

        if intent.use_collateral:
            actual = core._do_repay_collateral(
                ctrl, c.user, max_value(int256), intent.shrink,
                intent.swap_min_out, _callbacker, _route,
            )
        else:
            d: uint256 = core._slice(h, cap, _amount)
            actual = core._do_repay_wallet(
                ctrl, c.user, d, max_value(int256), intent.shrink
            )
    else:
        # pure collateral top-up; fill units = collateral
        assert intent.collateral_add > 0, "empty intent"
        cap = intent.collateral_add
        actual = core._slice(h, cap, _amount)
        core._do_add_collateral(ctrl, c.user, actual)

    lib._register_fill(h, c, cap, actual)
    core._post_health(ctrl, c.user, intent.min_health_after)

    fee: uint256 = 0
    if intent.debt_sub > 0:
        fee = core._pay_fee(c, staticcall ctrl.borrowed_token(), actual, msg.sender)
    else:
        fee = core._pay_fee(c, staticcall ctrl.collateral_token(), actual, msg.sender)
    log IntentFill(
        intent_hash=h, user=c.user, controller=c.controller,
        op=OP_REPAY, amount=actual, fee=fee, solver=msg.sender,
    )
