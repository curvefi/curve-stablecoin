# pragma version 0.4.3
"""
@title StableSwapNG LP EMA Oracle
@author Curve.Finance
@license Copyright (c) Curve.Finance, 2020-2026 - all rights reserved
@notice Prices the LP token of a 2-coin StableSwap-NG pool, quoted in the
        underlying asset of coin `COIN_IDX`. Each contract is specific to a
        single pool.

        The LP price is the pool's portfolio value (derived from the pool's
        internal `price_oracle`) scaled by the pool's `get_virtual_price()`.
        The virtual price is instantaneously manipulable - e.g. wash trading or
        a misbehaving rate oracle of a pool coin can momentarily inflate it. To
        defend against this while staying safe for collateral valuation the
        virtual price is dampened *asymmetrically*:

          - Upward moves are smoothed with an exponential moving average, so a
            momentary pump cannot lift the reported price within a block.
          - Downward moves are passed through immediately, so a genuine loss of
            value is never hidden behind a stale, too-high price (which would
            over-value collateral - the wrong failure mode).

        The virtual price used is `min(spot, ema)`, where `ema` grows up slowly
        (over `ema_time`) and is reset down to `spot` the moment `spot` falls
        below it.
@dev The pool's `price_oracle(0)` is capped at 2.0 (2e18) by the pool itself,
     so the reported price is capped accordingly. Calls can revert if
     `get_virtual_price()` reverts, e.g. because a coin's external rate oracle
     path fails.
@custom:security security@curve.finance
@custom:kill There is no need to kill this contract, just kill the underlying market
"""

from curve_std import ema
from curve_stablecoin.interfaces import IPriceOracle
from stableswap_ng import LPOracle as lp_oracle

implements: IPriceOracle
initializes: ema

POOL: public(immutable(lp_oracle.IStableSwapNG))
COIN_IDX: public(immutable(uint256))
# Identifier of the EMA tracking the pool virtual price (get_virtual_price()).
VIRTUAL_PRICE_EMA_ID: constant(String[4]) = "vp"


@deploy
def __init__(_pool: lp_oracle.IStableSwapNG, _i: uint256, _ema_time: uint256,):
    """
    @notice Set the priced pool and seed the virtual-price EMA with its current value.
    @param _pool StableSwap-NG pool (2 coins only) whose LP token is priced.
    @param _i Coin index used for quoting, 0 or 1. The price is quoted in
           the underlying asset of that coin: for a plain ERC20 coin this is the token
           itself, for a yield-bearing coin, e.g. `sA`, it is the underlying `A`.
    @param _ema_time Smoothing horizon (seconds) of the upside virtual-price EMA.
    """
    lp_oracle._sanity_check(_pool)
    assert _i < lp_oracle.N_COINS

    POOL = _pool
    COIN_IDX = _i

    ema.__init__(
        [
            ema.EMAConfig(
                ema_id=VIRTUAL_PRICE_EMA_ID,
                initial_value=staticcall POOL.get_virtual_price(),
                ema_time=_ema_time,
            )
        ]
    )


@internal
@view
def _virtual_price() -> uint256:
    """
    @notice Asymmetrically dampened pool virtual price used for read-only pricing.
    @dev Upside is the EMA-smoothed value, downside is the spot value -
         i.e. `min(spot, ema)`.
    """
    return min(staticcall POOL.get_virtual_price(), ema.read(VIRTUAL_PRICE_EMA_ID))


@internal
def _virtual_price_w() -> uint256:
    """
    @notice Asymmetrically dampened pool virtual price, persisting the EMA state.
    @dev On a downward move the EMA is reset to the spot value so that later
         upside smoothing starts from the new (lower) level, mirroring the
         read-only `min(spot, ema)` behaviour.
    """
    spot: uint256 = staticcall POOL.get_virtual_price()

    if spot < ema.read(VIRTUAL_PRICE_EMA_ID):
        # Downside: apply immediately and snap the EMA down to spot.
        # prev_value == queued_value == spot makes `read` return spot for any dt,
        # so this is a fully consistent EMA state.
        ema._emas[VIRTUAL_PRICE_EMA_ID] = ema.EMA(
            ema_time=ema._emas[VIRTUAL_PRICE_EMA_ID].ema_time,
            prev_value=spot,
            prev_timestamp=block.timestamp,
            queued_value=spot,
        )
        log ema.EmaUpdate(ema_id=VIRTUAL_PRICE_EMA_ID, prev_value=spot, queued_value=spot)
        return spot

    # Upside: smooth toward spot via the EMA's queueing update and report the
    # (still lagging) smoothed value.
    return ema.update(VIRTUAL_PRICE_EMA_ID, spot)


@external
@view
def price() -> uint256:
    """
    @notice LP token price: pool portfolio value scaled by the dampened virtual price.
    @return The manipulation-resistant LP price, 1e18-scaled and quoted in the
            underlying asset of coin `COIN_IDX`.
    """
    return lp_oracle._portfolio_value(POOL, COIN_IDX) * self._virtual_price() // lp_oracle.PRECISION


@external
def price_w() -> uint256:
    """
    @notice Same as `price`, but persists the virtual-price EMA state.
    @return The manipulation-resistant LP price, 1e18-scaled and quoted in the
            underlying asset of coin `COIN_IDX`.
    """
    return lp_oracle._portfolio_value(POOL, COIN_IDX) * self._virtual_price_w() // lp_oracle.PRECISION
