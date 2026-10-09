# pragma version 0.4.3
# pragma optimize codesize

"""
@title LlamaLend Intents — executor core (module)
@author Curve.Finance
@license Copyright (c) Curve.Finance, 2020-2026 - all rights reserved
@notice One intent type per IController operation (mirror API) + internal
        `_do_*` execution primitives shared with the 2-method executor.
        Deployable standalone via IntentExecutorMirror.vy.
@dev Requires `controller.approve(<executor>, True)` from the user.
     The solver route (callbacker, calldata) is never signed — only its
     bounds are: `swap_min_out` is a PRICE floor (output token wei per WAD
     of input token), so it composes with partial fills without pro-rata
     scaling; `min_health_after` is checked after every fill.
@custom:security security@curve.finance
@custom:kill pause() (admin) blocks all fills; cancels stay available.
"""

from curve_std.interfaces import IERC20
from curve_stablecoin.interfaces import IController
from curve_stablecoin.interfaces import IAMM

from curve_stablecoin.intents import intent_lib as lib

uses: lib


################################################################
#                          CONSTANTS                           #
################################################################

WAD: constant(uint256) = 10**18
BPS: constant(uint256) = 10**4
ROUTE_MAX: constant(uint256) = 4096
MAX_UINT: constant(uint256) = max_value(uint256)

# ops (event tagging)
OP_CREATE_LOAN: constant(uint8) = 1
OP_BORROW_MORE: constant(uint8) = 2
OP_ADD_COLLATERAL: constant(uint8) = 3
OP_REMOVE_COLLATERAL: constant(uint8) = 4
OP_REPAY: constant(uint8) = 5
OP_LIQUIDATE: constant(uint8) = 6

CREATE_LOAN_TYPEHASH: constant(bytes32) = keccak256(
    "CreateLoanIntent(Common common,uint256 collateral,uint256 debt,"
    "uint256 bands,uint256 swapMinOut,int256 minHealthAfter)"
    "Common(address user,address controller,uint256 priceBelow,"
    "uint256 priceAbove,int256 healthBelow,uint256 rateAbove,"
    "uint256 rateBelow,uint256 deadline,uint256 nonce,uint256 minFill,"
    "uint256 cooldown,uint256 feeStartBps,uint256 feeEndBps,uint256 decayStart)"
)
BORROW_MORE_TYPEHASH: constant(bytes32) = keccak256(
    "BorrowMoreIntent(Common common,uint256 collateral,uint256 debt,"
    "uint256 swapMinOut,int256 minHealthAfter)"
    "Common(address user,address controller,uint256 priceBelow,"
    "uint256 priceAbove,int256 healthBelow,uint256 rateAbove,"
    "uint256 rateBelow,uint256 deadline,uint256 nonce,uint256 minFill,"
    "uint256 cooldown,uint256 feeStartBps,uint256 feeEndBps,uint256 decayStart)"
)
ADD_COLLATERAL_TYPEHASH: constant(bytes32) = keccak256(
    "AddCollateralIntent(Common common,uint256 collateral)"
    "Common(address user,address controller,uint256 priceBelow,"
    "uint256 priceAbove,int256 healthBelow,uint256 rateAbove,"
    "uint256 rateBelow,uint256 deadline,uint256 nonce,uint256 minFill,"
    "uint256 cooldown,uint256 feeStartBps,uint256 feeEndBps,uint256 decayStart)"
)
REMOVE_COLLATERAL_TYPEHASH: constant(bytes32) = keccak256(
    "RemoveCollateralIntent(Common common,uint256 collateral,int256 minHealthAfter)"
    "Common(address user,address controller,uint256 priceBelow,"
    "uint256 priceAbove,int256 healthBelow,uint256 rateAbove,"
    "uint256 rateBelow,uint256 deadline,uint256 nonce,uint256 minFill,"
    "uint256 cooldown,uint256 feeStartBps,uint256 feeEndBps,uint256 decayStart)"
)
REPAY_TYPEHASH: constant(bytes32) = keccak256(
    "RepayIntent(Common common,uint256 debt,int256 maxActiveBand,bool shrink,"
    "bool useCollateral,uint256 swapMinOut,int256 minHealthAfter)"
    "Common(address user,address controller,uint256 priceBelow,"
    "uint256 priceAbove,int256 healthBelow,uint256 rateAbove,"
    "uint256 rateBelow,uint256 deadline,uint256 nonce,uint256 minFill,"
    "uint256 cooldown,uint256 feeStartBps,uint256 feeEndBps,uint256 decayStart)"
)
LIQUIDATE_TYPEHASH: constant(bytes32) = keccak256(
    "LiquidateIntent(Common common,uint256 minX,uint256 frac)"
    "Common(address user,address controller,uint256 priceBelow,"
    "uint256 priceAbove,int256 healthBelow,uint256 rateAbove,"
    "uint256 rateBelow,uint256 deadline,uint256 nonce,uint256 minFill,"
    "uint256 cooldown,uint256 feeStartBps,uint256 feeEndBps,uint256 decayStart)"
)


################################################################
#                           STRUCTS                            #
################################################################

struct CreateLoanIntent:
    common: lib.Common
    collateral: uint256      # pulled from user wallet
    debt: uint256            # one-shot cap == amount
    bands: uint256           # N
    swap_min_out: uint256    # leverage price floor (collateral wei per WAD debt); 0 = plain
    min_health_after: int256

struct BorrowMoreIntent:
    common: lib.Common
    collateral: uint256      # wallet collateral for the FULL intent (scaled pro-rata)
    debt: uint256            # cumulative cap, partial fills allowed
    swap_min_out: uint256
    min_health_after: int256

struct AddCollateralIntent:
    common: lib.Common
    collateral: uint256      # cumulative cap (collateral units)

struct RemoveCollateralIntent:
    common: lib.Common
    collateral: uint256      # cumulative cap (collateral units)
    min_health_after: int256

struct RepayIntent:
    common: lib.Common
    debt: uint256            # cumulative cap; MAX_UINT = full close
    max_active_band: int256
    shrink: bool
    use_collateral: bool     # repay out of position collateral (delever)
    swap_min_out: uint256    # delever price floor (borrowed wei per WAD collateral)
    min_health_after: int256

struct LiquidateIntent:
    common: lib.Common
    min_x: uint256           # forwarded to controller.liquidate
    frac: uint256            # WAD = full; one-shot


################################################################
#                            STATE                             #
################################################################

admin: public(address)
paused: public(bool)
# token => spender => infinite approval granted
_approved: HashMap[address, HashMap[address, bool]]


event IntentFill:
    intent_hash: indexed(bytes32)
    user: indexed(address)
    controller: indexed(address)
    op: uint8
    amount: uint256
    fee: uint256
    solver: address

event SetPaused:
    paused: bool


################################################################
#                            ADMIN                             #
################################################################

@deploy
def __init__(_admin: address):
    self.admin = _admin


@external
def set_paused(_paused: bool):
    assert msg.sender == self.admin, "admin only"
    self.paused = _paused
    log SetPaused(paused=_paused)


################################################################
#                       INTERNAL HELPERS                       #
################################################################

@internal
def _ensure_approval(_token: IERC20, _spender: address):
    if not self._approved[_token.address][_spender]:
        assert extcall _token.approve(_spender, MAX_UINT, default_return_value=True)
        self._approved[_token.address][_spender] = True


@internal
def _pull(_token: IERC20, _from: address, _amount: uint256):
    if _amount > 0:
        assert extcall _token.transferFrom(
            _from, self, _amount, default_return_value=True
        )


@internal
def _pre_fill(c: lib.Common, _h: bytes32):
    assert not self.paused, "paused"
    lib._check_valid(c, _h)
    lib._check_conditions(c)


@internal
def _pay_fee(
    c: lib.Common, _unit_token: IERC20, _units: uint256, _solver: address
) -> uint256:
    """Fee = Dutch-decayed bps of the filled units, paid user -> solver
    in the unit token of the operation (borrowed for debt ops,
    collateral for collateral-only ops)."""
    fee: uint256 = _units * lib._fee_bps(c) // BPS
    if fee > 0:
        assert extcall _unit_token.transferFrom(
            c.user, _solver, fee, default_return_value=True
        )
    return fee


@internal
def _post_health(_ctrl: IController, _user: address, _min_health: int256):
    if staticcall _ctrl.loan_exists(_user):
        assert staticcall _ctrl.health(_user, False) >= _min_health, "health"


@internal
@view
def _slice(_h: bytes32, _cap: uint256, _want: uint256) -> uint256:
    """MAX_UINT = fill whatever remains."""
    if _want == MAX_UINT:
        return lib._remaining(_h, _cap)
    return _want


################################################################
#              EXECUTION PRIMITIVES (shared _do_*)             #
################################################################

@internal
def _do_create_loan(
    _ctrl: IController,
    _user: address,
    _collateral: uint256,
    _debt: uint256,
    _bands: uint256,
    _swap_min_out: uint256,
    _callbacker: address,
    _route: Bytes[ROUTE_MAX],
):
    collateral_token: IERC20 = staticcall _ctrl.collateral_token()
    self._pull(collateral_token, _user, _collateral)
    self._ensure_approval(collateral_token, _ctrl.address)

    state0: uint256[4] = staticcall _ctrl.user_state(_user)
    extcall _ctrl.create_loan(_collateral, _debt, _bands, _user, _callbacker, _route)

    if _callbacker != empty(address) and _swap_min_out > 0:
        state1: uint256[4] = staticcall _ctrl.user_state(_user)
        gained: uint256 = state1[0] - state0[0] - _collateral
        assert gained >= _debt * _swap_min_out // WAD, "swap out"


@internal
def _do_borrow_more(
    _ctrl: IController,
    _user: address,
    _collateral: uint256,
    _debt: uint256,
    _swap_min_out: uint256,
    _callbacker: address,
    _route: Bytes[ROUTE_MAX],
):
    collateral_token: IERC20 = staticcall _ctrl.collateral_token()
    self._pull(collateral_token, _user, _collateral)
    self._ensure_approval(collateral_token, _ctrl.address)

    state0: uint256[4] = staticcall _ctrl.user_state(_user)
    extcall _ctrl.borrow_more(_collateral, _debt, _user, _callbacker, _route)

    if _callbacker != empty(address) and _swap_min_out > 0:
        state1: uint256[4] = staticcall _ctrl.user_state(_user)
        gained: uint256 = state1[0] - state0[0] - _collateral
        assert gained >= _debt * _swap_min_out // WAD, "swap out"


@internal
def _do_add_collateral(_ctrl: IController, _user: address, _amount: uint256):
    collateral_token: IERC20 = staticcall _ctrl.collateral_token()
    self._pull(collateral_token, _user, _amount)
    self._ensure_approval(collateral_token, _ctrl.address)
    extcall _ctrl.add_collateral(_amount, _user)


@internal
def _do_remove_collateral(_ctrl: IController, _user: address, _amount: uint256):
    # controller sends collateral directly to `_for` == user
    extcall _ctrl.remove_collateral(_amount, _user)


@internal
def _do_repay_wallet(
    _ctrl: IController,
    _user: address,
    _d_debt: uint256,
    _max_active_band: int256,
    _shrink: bool,
) -> uint256:
    d: uint256 = _d_debt
    debt: uint256 = staticcall _ctrl.debt(_user)
    if d > debt:
        d = debt  # full repayment
    borrowed_token: IERC20 = staticcall _ctrl.borrowed_token()
    self._pull(borrowed_token, _user, d)
    self._ensure_approval(borrowed_token, _ctrl.address)
    extcall _ctrl.repay(d, _user, _max_active_band, empty(address), b"", _shrink)
    return d


@internal
def _do_repay_collateral(
    _ctrl: IController,
    _user: address,
    _max_active_band: int256,
    _shrink: bool,
    _swap_min_out: uint256,
    _callbacker: address,
    _route: Bytes[ROUTE_MAX],
) -> uint256:
    """Delever: repay out of position collateral via solver callback.
    Returns actual debt reduction (the fill amount)."""
    assert _callbacker != empty(address), "no callbacker"
    state0: uint256[4] = staticcall _ctrl.user_state(_user)
    extcall _ctrl.repay(0, _user, _max_active_band, _callbacker, _route, _shrink)

    debt_cut: uint256 = 0
    if staticcall _ctrl.loan_exists(_user):
        state1: uint256[4] = staticcall _ctrl.user_state(_user)
        debt_cut = state0[2] - state1[2]
        coll_spent: uint256 = state0[0] - state1[0]
        assert debt_cut * WAD >= coll_spent * _swap_min_out, "swap out"
    else:
        # position fully closed; leftovers went to the user per controller flow
        debt_cut = state0[2]
    return debt_cut


@internal
def _do_liquidate(
    _ctrl: IController,
    _user: address,
    _min_x: uint256,
    _frac: uint256,
    _callbacker: address,
    _route: Bytes[ROUTE_MAX],
) -> uint256:
    """Self-liquidate on behalf of user (executor is an approved spender,
    so the health gate is bypassed by design). Returns debt closed."""
    debt0: uint256 = staticcall _ctrl.debt(_user)
    if _callbacker == empty(address):
        # controller pulls the borrowed shortfall from msg.sender: prefund from user
        to_pull: uint256 = staticcall _ctrl.tokens_to_liquidate(_user, _frac)
        borrowed_token: IERC20 = staticcall _ctrl.borrowed_token()
        self._pull(borrowed_token, _user, to_pull)
        self._ensure_approval(borrowed_token, _ctrl.address)
    extcall _ctrl.liquidate(_user, _min_x, _frac, _callbacker, _route)

    debt1: uint256 = 0
    if staticcall _ctrl.loan_exists(_user):
        debt1 = staticcall _ctrl.debt(_user)
    return debt0 - debt1


################################################################
#                  MIRROR EXTERNAL API (1:1)                   #
################################################################

@external
@nonreentrant
def create_loan(
    intent: CreateLoanIntent,
    _sig: Bytes[65],
    _callbacker: address = empty(address),
    _route: Bytes[ROUTE_MAX] = b"",
):
    c: lib.Common = intent.common
    h: bytes32 = lib._digest(
        keccak256(
            abi_encode(
                CREATE_LOAN_TYPEHASH,
                lib._hash_common(c),
                intent.collateral,
                intent.debt,
                intent.bands,
                intent.swap_min_out,
                intent.min_health_after,
            )
        )
    )
    self._pre_fill(c, h)
    lib._verify_sig(c.user, h, _sig)

    ctrl: IController = IController(c.controller)
    self._do_create_loan(
        ctrl, c.user, intent.collateral, intent.debt, intent.bands,
        intent.swap_min_out, _callbacker, _route,
    )
    lib._register_fill(h, c, intent.debt, intent.debt)  # one-shot
    self._post_health(ctrl, c.user, intent.min_health_after)
    fee: uint256 = self._pay_fee(
        c, staticcall ctrl.borrowed_token(), intent.debt, msg.sender
    )
    log IntentFill(
        intent_hash=h, user=c.user, controller=c.controller,
        op=OP_CREATE_LOAN, amount=intent.debt, fee=fee, solver=msg.sender,
    )


@external
@nonreentrant
def borrow_more(
    intent: BorrowMoreIntent,
    _sig: Bytes[65],
    _amount: uint256,  # debt slice; MAX_UINT = remaining
    _callbacker: address = empty(address),
    _route: Bytes[ROUTE_MAX] = b"",
):
    c: lib.Common = intent.common
    h: bytes32 = lib._digest(
        keccak256(
            abi_encode(
                BORROW_MORE_TYPEHASH,
                lib._hash_common(c),
                intent.collateral,
                intent.debt,
                intent.swap_min_out,
                intent.min_health_after,
            )
        )
    )
    self._pre_fill(c, h)
    lib._verify_sig(c.user, h, _sig)

    d: uint256 = self._slice(h, intent.debt, _amount)
    coll: uint256 = intent.collateral * d // intent.debt  # pro-rata wallet leg
    ctrl: IController = IController(c.controller)
    self._do_borrow_more(
        ctrl, c.user, coll, d, intent.swap_min_out, _callbacker, _route
    )
    lib._register_fill(h, c, intent.debt, d)
    self._post_health(ctrl, c.user, intent.min_health_after)
    fee: uint256 = self._pay_fee(c, staticcall ctrl.borrowed_token(), d, msg.sender)
    log IntentFill(
        intent_hash=h, user=c.user, controller=c.controller,
        op=OP_BORROW_MORE, amount=d, fee=fee, solver=msg.sender,
    )


@external
@nonreentrant
def add_collateral(
    intent: AddCollateralIntent,
    _sig: Bytes[65],
    _amount: uint256,  # collateral slice; MAX_UINT = remaining
):
    c: lib.Common = intent.common
    h: bytes32 = lib._digest(
        keccak256(
            abi_encode(ADD_COLLATERAL_TYPEHASH, lib._hash_common(c), intent.collateral)
        )
    )
    self._pre_fill(c, h)
    lib._verify_sig(c.user, h, _sig)

    d: uint256 = self._slice(h, intent.collateral, _amount)
    ctrl: IController = IController(c.controller)
    self._do_add_collateral(ctrl, c.user, d)
    lib._register_fill(h, c, intent.collateral, d)
    fee: uint256 = self._pay_fee(c, staticcall ctrl.collateral_token(), d, msg.sender)
    log IntentFill(
        intent_hash=h, user=c.user, controller=c.controller,
        op=OP_ADD_COLLATERAL, amount=d, fee=fee, solver=msg.sender,
    )


@external
@nonreentrant
def remove_collateral(
    intent: RemoveCollateralIntent,
    _sig: Bytes[65],
    _amount: uint256,  # collateral slice; MAX_UINT = remaining
):
    c: lib.Common = intent.common
    h: bytes32 = lib._digest(
        keccak256(
            abi_encode(
                REMOVE_COLLATERAL_TYPEHASH,
                lib._hash_common(c),
                intent.collateral,
                intent.min_health_after,
            )
        )
    )
    self._pre_fill(c, h)
    lib._verify_sig(c.user, h, _sig)

    d: uint256 = self._slice(h, intent.collateral, _amount)
    ctrl: IController = IController(c.controller)
    self._do_remove_collateral(ctrl, c.user, d)
    lib._register_fill(h, c, intent.collateral, d)
    self._post_health(ctrl, c.user, intent.min_health_after)
    fee: uint256 = self._pay_fee(c, staticcall ctrl.collateral_token(), d, msg.sender)
    log IntentFill(
        intent_hash=h, user=c.user, controller=c.controller,
        op=OP_REMOVE_COLLATERAL, amount=d, fee=fee, solver=msg.sender,
    )


@external
@nonreentrant
def repay(
    intent: RepayIntent,
    _sig: Bytes[65],
    _amount: uint256,  # debt slice; MAX_UINT = remaining
    _callbacker: address = empty(address),
    _route: Bytes[ROUTE_MAX] = b"",
):
    c: lib.Common = intent.common
    h: bytes32 = lib._digest(
        keccak256(
            abi_encode(
                REPAY_TYPEHASH,
                lib._hash_common(c),
                intent.debt,
                intent.max_active_band,
                intent.shrink,
                intent.use_collateral,
                intent.swap_min_out,
                intent.min_health_after,
            )
        )
    )
    self._pre_fill(c, h)
    lib._verify_sig(c.user, h, _sig)

    ctrl: IController = IController(c.controller)
    actual: uint256 = 0
    if intent.use_collateral:
        actual = self._do_repay_collateral(
            ctrl, c.user, intent.max_active_band, intent.shrink,
            intent.swap_min_out, _callbacker, _route,
        )
    else:
        d: uint256 = self._slice(h, intent.debt, _amount)
        actual = self._do_repay_wallet(
            ctrl, c.user, d, intent.max_active_band, intent.shrink
        )
    lib._register_fill(h, c, intent.debt, actual)
    self._post_health(ctrl, c.user, intent.min_health_after)
    fee: uint256 = self._pay_fee(c, staticcall ctrl.borrowed_token(), actual, msg.sender)
    log IntentFill(
        intent_hash=h, user=c.user, controller=c.controller,
        op=OP_REPAY, amount=actual, fee=fee, solver=msg.sender,
    )


@external
@nonreentrant
def liquidate(
    intent: LiquidateIntent,
    _sig: Bytes[65],
    _callbacker: address = empty(address),
    _route: Bytes[ROUTE_MAX] = b"",
):
    c: lib.Common = intent.common
    h: bytes32 = lib._digest(
        keccak256(
            abi_encode(
                LIQUIDATE_TYPEHASH, lib._hash_common(c), intent.min_x, intent.frac
            )
        )
    )
    self._pre_fill(c, h)
    lib._verify_sig(c.user, h, _sig)

    ctrl: IController = IController(c.controller)
    closed: uint256 = self._do_liquidate(
        ctrl, c.user, intent.min_x, intent.frac, _callbacker, _route
    )
    lib._register_fill(h, c, WAD, WAD)  # one-shot
    fee: uint256 = self._pay_fee(c, staticcall ctrl.borrowed_token(), closed, msg.sender)
    log IntentFill(
        intent_hash=h, user=c.user, controller=c.controller,
        op=OP_LIQUIDATE, amount=closed, fee=fee, solver=msg.sender,
    )


################################################################
#                     CANCELLATION & VIEWS                     #
################################################################

@external
def cancel(_word: uint256, _mask: uint256):
    """Invalidate nonces for msg.sender (kills remaining fills)."""
    lib._cancel(msg.sender, _word, _mask)


@external
@view
def intent_filled(_h: bytes32) -> uint256:
    return lib.filled[_h]


@external
@view
def is_cancelled(_user: address, _nonce: uint256) -> bool:
    return lib.nonce_bitmap[_user][_nonce >> 8] & (1 << (_nonce & 255)) != 0
