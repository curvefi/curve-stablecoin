# pragma version 0.4.3
"""
@title ERC4626 EMA Oracle
@author Curve.Finance
@license Copyright (c) Curve.Finance, 2020-2026 - all rights reserved
@notice Prices an ERC4626 vault share, quoted in the vault's underlying asset.
        Each contract is specific to a single vault.

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
@dev `price` and `price_w` return the same value within a block, only `price_w`
     persists the EMA state, so the smoothed value advances only as often as
     `price_w` is called. Calls revert if `convertToAssets` reverts.

     The vault must have the same number of decimals as its underlying asset,
     which is what makes `convertToAssets(1e18)` a 1e18-scaled price (the
     decimals cancel). A vault with a decimals offset - e.g. OpenZeppelin's
     `_decimalsOffset()`, i.e. virtual shares - reports a price off by
     `10**offset` with no revert anywhere, so check this before deploying.
@custom:security security@curve.finance
@custom:kill There is no need to kill this contract, just kill the underlying market
"""

from curve_std import ema
from curve_stablecoin.interfaces import IPriceOracle
from curve_stablecoin import constants as c

implements: IPriceOracle
initializes: ema

interface ERC4626:
    def convertToAssets(_shares: uint256) -> uint256: view


VAULT: public(immutable(ERC4626))

WAD: constant(uint256) = c.WAD
# Identifier of the EMA tracking the ERC4626 share price (convertToAssets(1e18)).
SHARE_PRICE_EMA_ID: constant(String[4]) = "shp"


@deploy
def __init__(
    _vault: ERC4626,
    _ema_time: uint256,
):
    """
    @notice Set the priced vault and seed the share-price EMA with its current value.
    @param _vault ERC4626 vault whose `convertToAssets(1e18)` gives the share price.
    @param _ema_time Smoothing horizon (seconds) of the upside share-price EMA.
    """
    VAULT = _vault

    # Basic sanity check for the required vault method.
    share_price: uint256 = staticcall _vault.convertToAssets(WAD)
    assert share_price > 0  # dev: invalid share price

    ema.__init__(
        [
            ema.EMAConfig(
                ema_id=SHARE_PRICE_EMA_ID,
                initial_value=share_price,
                ema_time=_ema_time,
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
    return min(staticcall VAULT.convertToAssets(WAD), ema.read(SHARE_PRICE_EMA_ID))


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
        # Downside: apply immediately and snap the EMA down to spot.
        # prev_value == queued_value == spot makes `read` return spot for any dt,
        # so this is a fully consistent EMA state.
        ema._emas[SHARE_PRICE_EMA_ID] = ema.EMA(
            ema_time=ema._emas[SHARE_PRICE_EMA_ID].ema_time,
            prev_value=spot,
            prev_timestamp=block.timestamp,
            queued_value=spot,
        )
        log ema.EmaUpdate(ema_id=SHARE_PRICE_EMA_ID, prev_value=spot, queued_value=spot)
        return spot

    # Upside: smooth toward spot via the EMA's queueing update and report the
    # (still lagging) smoothed value.
    return ema.update(SHARE_PRICE_EMA_ID, spot)


@external
@view
def price() -> uint256:
    """
    @notice Dampened ERC4626 share price.
    @return The manipulation-resistant share price, 1e18-scaled and quoted in
            the vault's underlying asset.
    """
    return self._share_price()


@external
def price_w() -> uint256:
    """
    @notice Same as `price`, but persists the share-price EMA state.
    @return The manipulation-resistant share price, 1e18-scaled and quoted in
            the vault's underlying asset.
    """
    return self._share_price_w()
