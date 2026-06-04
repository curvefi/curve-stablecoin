# pragma version 0.4.3
# pragma nonreentrancy on
"""
@title Peg Keeper V2 Read-Only Lens
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2025 - all rights reserved
@notice Stateless view contract that wraps a single PegKeeperV2 with the
    views external keepers and dashboards otherwise reconstruct off-chain:
        - direction (provide / withdraw) and size of the next update()
        - which precondition currently blocks update() (cooldown, regulator
          ban, perfectly balanced pool, or unprofitable call)
        - oriented EMA price of the pegged coin, regardless of its pool index
        - absolute peg deviation in basis points
        - on-chain countdown until the next update() unlocks
    The lens reads only public views on PegKeeperV2, its Regulator, and the
    underlying StableSwap pool. It holds no state and is safe to deploy
    alongside any existing PegKeeperV2 deployment without re-audit.
@dev
    estimate_update() mirrors PegKeeperV2.update() arithmetic line-for-line
    so the returned (action, amount) matches the next on-chain call within
    1 wei. PegKeeperV2's existing estimate_caller_profit() collapses three
    distinct silent-no-op reasons (cooldown not elapsed, regulator returned
    0, exactly balanced pool) and one revert reason ("peg unprofitable")
    into a single returned 0; the BLOCKER_* code disambiguates them.

    Decimal handling. PegKeeperV2 normalises the non-pegged balance via
        balance_peg = pool.balances(1 - I) * PEG_MUL
    where PEG_MUL = 10**(18 - other_coin.decimals()) and PEGGED is fixed
    at 18 decimals. PEG_MUL is not exposed by PegKeeperV2; the lens
    recomputes it from the other coin's decimals() at deploy.

    Index orientation. PegKeeperV2 stores I privately and exposes only
    IS_INVERSE (= I == 0). The lens recovers I from IS_INVERSE and
    asserts pool.coins(I) == pegged at deploy.

    Pool dialect. PegKeeperV2.IS_NG is snapshotted at construction so the
    oracle view dispatches to the correct price_oracle signature without
    re-detection at every read.
@custom:security security@curve.fi
@custom:kill Stateless contract doesn't need to be killed.
"""

from curve_std.interfaces import IERC20

from curve_stablecoin.interfaces import IPegKeeperV2
from curve_stablecoin.interfaces import IPegKeeperRegulator


# Inline pool interfaces — IStablePool.vyi does not expose balances().
interface CurvePool:
    def balances(i: uint256) -> uint256: view
    def coins(i: uint256) -> address: view

interface CurvePoolNG:
    def price_oracle(i: uint256) -> uint256: view

interface CurvePoolOld:
    def price_oracle() -> uint256: view


# ------------------------------------------------------------------
#                            CONSTANTS
# ------------------------------------------------------------------

PRECISION: public(constant(uint256)) = 10**18
BPS_SCALE: public(constant(uint256)) = 10_000

# update() direction returned by estimate_update().
ACTION_NOOP: public(constant(uint256)) = 0
ACTION_PROVIDE: public(constant(uint256)) = 1
ACTION_WITHDRAW: public(constant(uint256)) = 2

# update() blocker — reason the next call would not move tokens this block.
BLOCKER_READY: public(constant(uint256)) = 0
BLOCKER_COOLDOWN: public(constant(uint256)) = 1
BLOCKER_REGULATOR: public(constant(uint256)) = 2
BLOCKER_BALANCED: public(constant(uint256)) = 3
BLOCKER_UNPROFITABLE: public(constant(uint256)) = 4


struct UpdatePreview:
    action: uint256        # ACTION_*: direction the next update() would take
    amount: uint256        # pegged tokens that would be provided or withdrawn
    caller_profit: uint256 # LP tokens that would be sent to the caller
    blocker: uint256       # BLOCKER_*: which precondition currently blocks update()


# ------------------------------------------------------------------
#                            IMMUTABLES
# ------------------------------------------------------------------

PEG_KEEPER: public(immutable(IPegKeeperV2))
REGULATOR: public(immutable(IPegKeeperRegulator))
POOL: public(immutable(CurvePool))
PEGGED: public(immutable(IERC20))
# Index of the pegged token in the pool (0 or 1).
I: public(immutable(uint256))
I_OTHER: public(immutable(uint256))
# 10**(18 - other_coin.decimals()), to normalise the non-pegged balance.
PEG_MUL: public(immutable(uint256))
# Snapshot of PegKeeperV2.IS_NG so the lens dispatches to the right
# price_oracle signature without re-detecting it on every read.
IS_NG: public(immutable(bool))


# ------------------------------------------------------------------
#                           CONSTRUCTOR
# ------------------------------------------------------------------

@deploy
def __init__(_peg_keeper: IPegKeeperV2):
    """
    @param _peg_keeper A deployed PegKeeperV2 instance.
    """
    PEG_KEEPER = _peg_keeper
    REGULATOR = IPegKeeperRegulator(staticcall _peg_keeper.regulator())

    pool: address = staticcall _peg_keeper.pool()
    pegged: address = staticcall _peg_keeper.pegged()
    is_inverse: bool = staticcall _peg_keeper.IS_INVERSE()
    is_ng: bool = staticcall _peg_keeper.IS_NG()

    POOL = CurvePool(pool)
    PEGGED = IERC20(pegged)
    IS_NG = is_ng

    # PegKeeperV2 sets I to the index where coins[i] == pegged and stores
    # IS_INVERSE = (i == 0). Recover I from IS_INVERSE.
    i: uint256 = 0 if is_inverse else 1
    I = i
    I_OTHER = 1 - i

    # The keeper's view of which slot holds pegged must agree with the pool's
    # view. Catches a swapped (keeper, pool) pairing at deploy rather than
    # at first dashboard read.
    assert staticcall CurvePool(pool).coins(i) == pegged, "Lens: pegged index mismatch"

    # PegKeeperV2 itself reverts at construction when the other coin has more
    # than 18 decimals (the 10**(18 - decimals) calculation underflows), so the
    # lens does not need a redundant guard — the keeper would never exist.
    other: address = staticcall CurvePool(pool).coins(1 - i)
    other_decimals: uint256 = convert(staticcall IERC20(other).decimals(), uint256)
    PEG_MUL = 10 ** (18 - other_decimals)


# ------------------------------------------------------------------
#                         ORIENTED PRICE
# ------------------------------------------------------------------

@internal
@view
def _raw_oracle() -> uint256:
    if IS_NG:
        return staticcall CurvePoolNG(POOL.address).price_oracle(0)
    return staticcall CurvePoolOld(POOL.address).price_oracle()


@internal
@view
def _pegged_price() -> uint256:
    """
    Oriented oracle: returns the EMA value of 1 PEGGED in units of the other
    coin, 1e18-based. When pegged is coin 0 (IS_INVERSE) we flip price_oracle's
    "value of coin 1 in coin 0" convention, matching the regulator's
    _get_price_oracle.
    """
    raw: uint256 = self._raw_oracle()
    if I == 1:
        return raw
    return PRECISION * PRECISION // raw


@external
@view
def pegged_price() -> uint256:
    """
    @notice EMA price of 1 PEGGED in units of the other pool coin, 1e18 base.
    @dev Orientation is corrected for PegKeeperV2.IS_INVERSE: callers always
         read the price of the *pegged* coin, regardless of its pool index.
    """
    return self._pegged_price()


@external
@view
def peg_deviation_bps() -> uint256:
    """
    @notice Absolute deviation of the oriented EMA from $1, in basis points.
    @dev Symmetric: a 25 bps premium and a 25 bps discount both return 25.
         Reads the same oracle PegKeeperV2.update() reads, so the bps value
         tracks the keeper's signal source rather than the AggregateStablePrice
         feed used for collateral pricing.
    """
    price: uint256 = self._pegged_price()
    if price >= PRECISION:
        return (price - PRECISION) * BPS_SCALE // PRECISION
    return (PRECISION - price) * BPS_SCALE // PRECISION


# ------------------------------------------------------------------
#                         COOLDOWN VIEW
# ------------------------------------------------------------------

@external
@view
def next_action_eta() -> uint256:
    """
    @notice Earliest block.timestamp at which PegKeeperV2.update() unlocks.
    @dev Returns block.timestamp when the cooldown has already elapsed, so
         callers can treat the value uniformly as max(now, eta).
    """
    eta: uint256 = (
        staticcall PEG_KEEPER.last_change() + staticcall PEG_KEEPER.action_delay()
    )
    if eta < block.timestamp:
        return block.timestamp
    return eta


# ------------------------------------------------------------------
#                         UPDATE PREVIEW
# ------------------------------------------------------------------

@internal
@view
def _estimate_update() -> UpdatePreview:
    preview: UpdatePreview = UpdatePreview(
        action=ACTION_NOOP, amount=0, caller_profit=0, blocker=BLOCKER_READY
    )

    last: uint256 = staticcall PEG_KEEPER.last_change()
    delay: uint256 = staticcall PEG_KEEPER.action_delay()
    if last + delay > block.timestamp:
        preview.blocker = BLOCKER_COOLDOWN
        return preview

    balance_pegged: uint256 = staticcall POOL.balances(I)
    balance_peg: uint256 = staticcall POOL.balances(I_OTHER) * PEG_MUL

    if balance_pegged == balance_peg:
        # update() would still take the withdraw branch (balance_peg > balance_pegged
        # is False), pass amount=0 to _withdraw, and revert "peg unprofitable".
        preview.blocker = BLOCKER_BALANCED
        return preview

    is_provide: bool = balance_peg > balance_pegged
    desired: uint256 = 0
    allowed: uint256 = 0
    if is_provide:
        preview.action = ACTION_PROVIDE
        desired = (balance_peg - balance_pegged) // 5
        allowed = staticcall REGULATOR.provide_allowed(PEG_KEEPER.address)
    else:
        preview.action = ACTION_WITHDRAW
        desired = (balance_pegged - balance_peg) // 5
        allowed = staticcall REGULATOR.withdraw_allowed(PEG_KEEPER.address)

    if allowed == 0:
        preview.blocker = BLOCKER_REGULATOR
        return preview

    preview.amount = min(desired, allowed)

    # PegKeeperV2.update() reverts with "peg unprofitable" when the call would
    # not increase calc_profit(). estimate_caller_profit() returns 0 in that
    # case (it also returns 0 during cooldown and on regulator ban, but those
    # paths are handled above, so the only remaining 0-source is unprofitability).
    caller_profit: uint256 = staticcall PEG_KEEPER.estimate_caller_profit()
    preview.caller_profit = caller_profit
    if caller_profit == 0:
        preview.blocker = BLOCKER_UNPROFITABLE

    return preview


@external
@view
def estimate_update() -> UpdatePreview:
    """
    @notice Preview the next PegKeeperV2.update() without state change.
    @dev Mirrors PegKeeperV2.update() arithmetic exactly: balances → integer
         division by 5 → regulator cap → caller_share cut. `amount` matches
         the next on-chain action within 1 wei. `blocker` distinguishes the
         four reasons update() may not move tokens this block, which the
         keeper's own estimate_caller_profit() returns as a single 0:
           READY        update() will succeed and pay the caller
           COOLDOWN     action_delay has not elapsed
           REGULATOR    provide_allowed / withdraw_allowed returned 0
           BALANCED     pool balances are exactly equal in 18-dec terms
           UNPROFITABLE the call would not increase calc_profit()
    @return preview Direction (ACTION_*), pegged amount, caller LP profit,
            and the BLOCKER_* code explaining the outcome.
    """
    return self._estimate_update()


@external
@view
def update_blocker() -> uint256:
    """
    @notice BLOCKER_* code for the next update() — a scalar shorthand for
            monitors that only need the gate state.
    """
    return self._estimate_update().blocker
