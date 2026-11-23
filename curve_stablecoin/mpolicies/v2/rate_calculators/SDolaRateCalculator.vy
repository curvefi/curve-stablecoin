#pragma version 0.4.3

"""
@title sDOLA Rate Calculator
@author Inverse Finance
@notice Provides a per-second yield rate for sDOLA, based on the previous week's revenue and current total assets
@custom:kill There is no need to kill this contract, just kill the underlying market
"""

from curve_stablecoin.interfaces import IRateCalculator

implements: IRateCalculator


interface ISDola:
    def totalAssets() -> uint256: view
    def weeklyRevenue(week: uint256) -> uint256: view


WEEK: constant(uint256) = 7 * 86400

SDOLA: public(immutable(ISDola))


@deploy
def __init__(_sdola: address):
    """
    @param _sdola Address of the sDOLA vault contract
    @notice Initializes the rate calculator with the sDOLA contract address
    """
    SDOLA = ISDola(_sdola)


@internal
@view
def _rate() -> uint256:
    """
    @notice Calculates the current per-second rate for sDOLA
    @return rate Yield per second, scaled by 1e18
    """
    assets: uint256 = staticcall SDOLA.totalAssets()
    if assets == 0:
        return 0

    current_week: uint256 = block.timestamp // WEEK
    weekly_revenue: uint256 = staticcall SDOLA.weeklyRevenue(current_week - 1)
    sdola_per_second: uint256 = weekly_revenue // WEEK

    return sdola_per_second * 10**18 // assets


@external
@view
def rate() -> uint256:
    """
    @notice Read-only current per-second rate for sDOLA
    @return rate Yield per second, scaled by 1e18
    """
    return self._rate()


@external
def rate_w() -> uint256:
    """
    @notice Current per-second rate for sDOLA
    @dev Provided for interface compatibility with rate calculators that record
         state. sDOLA's rate is stateless, so this returns exactly the same value
         as `rate()` and writes nothing.
    @return rate Yield per second, scaled by 1e18
    """
    return self._rate()
