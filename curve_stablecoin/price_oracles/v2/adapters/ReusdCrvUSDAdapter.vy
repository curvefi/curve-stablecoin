# pragma version 0.4.3
"""
@title Capped reUSD/crvUSD Adapter
@author Curve.Finance
@license Copyright (c) Curve.Finance, 2020-2026 - all rights reserved
@notice Exposes the redemption-based reUSD feed as an IPriceOracle, capped at
        1 crvUSD per reUSD. Prices are 1e18-scaled and denominated in crvUSD.
@dev Ethereum Mainnet only: the underlying feed address is hardcoded.
     The feed's redemption floor is preserved and can mask market losses.
     This adapter adds no EMA; upstream call failures propagate to the caller.
@custom:security security@curve.finance
@custom:kill There is no need to kill this contract, just kill the underlying market
"""

from curve_stablecoin.interfaces import IPriceOracle
from curve_stablecoin import constants as c

implements: IPriceOracle

interface ReusdOracle:
    def priceAsCrvusd() -> uint256: view


REUSD_FEED: public(constant(ReusdOracle)) = ReusdOracle(0x07Ac1E016D4335FB833666ed5C43846162d2B7e8)
WAD: constant(uint256) = c.WAD


@internal
@view
def _price() -> uint256:
    return min(WAD, staticcall REUSD_FEED.priceAsCrvusd())


@external
@view
def price() -> uint256:
    """@notice Capped crvUSD per reUSD, scaled to 1e18."""
    return self._price()


@external
def price_w() -> uint256:
    """@notice Same as price(): neither the adapter nor this feed read holds EMA state."""
    return self._price()
