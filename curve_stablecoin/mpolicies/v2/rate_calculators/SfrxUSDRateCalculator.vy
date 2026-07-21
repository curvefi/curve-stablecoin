#pragma version 0.4.3
"""
@title sfrxUSD Rate Calculator
@author Curve.Finance
@license Copyright (c) Curve.Finance, 2020-2026 - all rights reserved
@notice Provides a per-second yield rate for sfrxUSD, based on current cycle data and stored assets
@custom:security security@curve.finance
@custom:kill There is no need to kill this contract, just kill the underlying market
"""

from curve_stablecoin.interfaces import IRateCalculator

implements: IRateCalculator


interface IFraxVault:
    def rewardsCycleData() -> (uint256, uint256, uint256): view
    def storedTotalAssets() -> uint256: view
    def maxDistributionPerSecondPerAsset() -> uint256: view


SFRXUSD: public(immutable(IFraxVault))


@deploy
def __init__(_sfrxusd: address):
    """
    @param _sfrxusd Address of the sfrxUSD vault contract
    @notice Initializes the rate calculator with the sfrxUSD contract address
    """
    SFRXUSD = IFraxVault(_sfrxusd)


@internal
@view
def _rate() -> uint256:
    """
    @notice Calculates the current per-second rate for sfrxUSD
    @return rate Yield per second, scaled by 1e18
    """
    cycle_end: uint256 = 0
    last_sync: uint256 = 0
    reward_amt: uint256 = 0
    cycle_end, last_sync, reward_amt = staticcall SFRXUSD.rewardsCycleData()

    # Prevent division by zero
    if cycle_end <= last_sync:
        return 0

    assets: uint256 = staticcall SFRXUSD.storedTotalAssets()
    if assets == 0:
        assets = 1

    max_distro: uint256 = staticcall SFRXUSD.maxDistributionPerSecondPerAsset()
    duration: uint256 = cycle_end - last_sync

    frax_per_second: uint256 = reward_amt // duration
    frax_per_second = frax_per_second * 10**18 // assets

    return min(frax_per_second, max_distro)


@external
@view
def rate() -> uint256:
    """
    @notice Read-only current per-second rate for sfrxUSD
    @return rate Yield per second, scaled by 1e18
    """
    return self._rate()


@external
def rate_w() -> uint256:
    """
    @notice Current per-second rate for sfrxUSD
    @dev Provided for interface compatibility with rate calculators that record
         state. sfrxUSD's rate is stateless, so this returns exactly the same value
         as `rate()` and writes nothing.
    @return rate Yield per second, scaled by 1e18
    """
    return self._rate()
