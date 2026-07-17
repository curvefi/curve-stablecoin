#pragma version 0.4.3
"""
@title SyrupUSDCAdapter
@author Curve.Finance
@license Copyright (c) Curve.Finance, 2020-2026 - all rights reserved
@notice Exposes SyrupUSDC as an ERC4626-style `convertToAssets`
"""

interface ISyrupUSDC:
    def convertToExitAssets(_shares: uint256) -> uint256: view

SYRUP_USDC: constant(ISyrupUSDC) = ISyrupUSDC(0x80ac24aA929eaF5013f6436cdA2a7ba190f5Cc0b)


@external
@view
def convertToAssets(_shares: uint256) -> uint256:
    """
    @notice Returns the amount of exit assets for the input amount.
    @dev Uses `convertToExitAssets` (net of exit fees), NOT `convertToAssets`:
         this reports a lower, conservative price, which is the safe direction
         for collateral valuation. Do not "simplify" it to `convertToAssets`.
    @param _shares Amount of shares to convert
    @return Amount of assets equivalent to shares
    """
    return staticcall SYRUP_USDC.convertToExitAssets(_shares)
