# pragma version 0.4.3
"""
@title ERC4626 EMA Wrapper
@author Curve.Finance
@license Copyright (c) Curve.Finance, 2020-2026 - all rights reserved
@notice Chains an external oracle with an ERC4626 vault's share price.

        The ERC4626 share price (`convertToAssets(1e18)`) is instantaneously
        manipulable - e.g. a donation/pump can momentarily inflate it.  To
        defend against this while staying safe for collateral valuation the
        share price is dampened *asymmetrically*:

          - Upward moves are smoothed with an exponential moving average, so a
            momentary pump cannot lift the reported price within a block.
          - Downward moves are passed through immediately, so a genuine loss of
            value is never hidden behind a stale, too-high price (which would
            over-value collateral - the wrong failure mode).

        The reported share price is `min(spot, ema)`, where `ema`
        grows up slowly (over `ema_time`) and is reset down to `spot` the
        moment `spot` falls below it.
"""

from curve_std import ema

initializes: ema


interface Oracle:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable


interface ERC4626:
    def convertToAssets(shares: uint256) -> uint256: view


ORACLE: public(immutable(Oracle))
VAULT: public(immutable(ERC4626))

WAD: constant(uint256) = 10**18
# Identifier of the EMA tracking the ERC4626 share price (convertToAssets(1e18)).
SHARE_PRICE_EMA_ID: constant(String[4]) = "shp"


@deploy
def __init__(
    oracle: Oracle,
    vault: ERC4626,
    ema_time: uint256,
):
    ORACLE = oracle
    VAULT = vault

    ema.__init__(
        [
            ema.EMAConfig(
                ema_id=SHARE_PRICE_EMA_ID,
                initial_value=staticcall vault.convertToAssets(WAD),
                ema_time=ema_time,
            )
        ]
    )


@internal
@view
def _share_price() -> uint256:
    """
    @notice Asymmetrically dampened share price used for read-only pricing.
    @dev Upside is the EMA-smoothed value, downside is the spot value -
         i.e. `min(spot, ema)`.
    """
    spot: uint256 = staticcall VAULT.convertToAssets(WAD)
    return min(spot, ema.read(SHARE_PRICE_EMA_ID))


@internal
def _share_price_w() -> uint256:
    """
    @notice Asymmetrically dampened share price, persisting the EMA state.
    @dev On a downward move the EMA is reset to the spot value so that later
         upside smoothing starts from the new (lower) level, mirroring the
         read-only `min(spot, ema)` behaviour.
    """
    spot: uint256 = staticcall VAULT.convertToAssets(WAD)

    if spot < ema.read(SHARE_PRICE_EMA_ID):
        # Downside (or flat): apply immediately and snap the EMA down to spot.
        # prev_value == queued_value == spot makes `read` return spot for any dt,
        # so this is a fully consistent EMA state.
        ema._emas[SHARE_PRICE_EMA_ID] = ema.EMA(
            ema_time=ema._emas[SHARE_PRICE_EMA_ID].ema_time,
            prev_value=spot,
            prev_timestamp=block.timestamp,
            queued_value=spot,
        )
        return spot

    # Upside: smooth toward spot via the EMA's queueing update and report the
    # (still lagging) smoothed value.
    return ema.update(SHARE_PRICE_EMA_ID, spot)


@external
@view
def price() -> uint256:
    p1: uint256 = staticcall ORACLE.price()
    return p1 * self._share_price() // WAD


@external
def price_w() -> uint256:
    p1: uint256 = extcall ORACLE.price_w()
    return p1 * self._share_price_w() // WAD
