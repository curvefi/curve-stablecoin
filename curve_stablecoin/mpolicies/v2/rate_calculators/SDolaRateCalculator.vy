#pragma version 0.4.3

"""
@title sDOLA Rate Calculator
@author Inverse Finance
@notice Provides a per-second yield rate for sDOLA, based on the previous week's revenue and current total assets
@custom:kill This rate calculator is bound to its monetary policy, and the monetary policy is bound to its Controller;
kill the Controller to halt new borrowing.
"""


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


@external
@view
def rate() -> uint256:
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
