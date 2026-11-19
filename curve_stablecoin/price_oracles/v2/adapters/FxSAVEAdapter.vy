#pragma version 0.4.3
"""
@title FxSAVEAdapter
@author Curve.Finance
@license Copyright (c) Curve.Finance, 2020-2026 - all rights reserved
@notice Exposes fxSAVE's NAV in fxUSD as an ERC4626-style `convertToAssets`
@dev Use this contract only on Ethereum Mainnet since the fxSAVE and fxSP addresses
     are hardcoded.
     NAV is the fxUSD and USDC behind fxSAVE's shares of fxSP (f(x)'s stability
     pool), with each USDC counted as one fxUSD. The USDC includes what fxSP
     lends on Aave. NAV is not net of fxSP's instant-redemption fee and reads
     no price oracle.
     fxSP sent to fxSAVE, or USDC sent to fxSP, raises it within a block, so
     read it through an oracle that smooths rises.
@custom:security security@curve.finance
@custom:kill There is no need to kill this contract, just kill the underlying market
"""

interface IFxSAVE:
    def convertToAssets(_shares: uint256) -> uint256: view

interface IFxSP:
    def previewRedeem(_shares: uint256) -> (uint256, uint256): view

FXSAVE: constant(IFxSAVE) = IFxSAVE(0x7743e50F534a7f9F1791DdE7dCD89F7783Eefc39)
FXSP: constant(IFxSP) = IFxSP(0x65C9A641afCEB9C0E6034e558A319488FA0FA3be)
# USDC has 6 decimals, fxUSD 18.
USDC_SCALE: constant(uint256) = 10**12


@external
@view
def convertToAssets(_shares: uint256) -> uint256:
    """
    @notice Returns the fxUSD value of the input amount of fxSAVE.
    @dev fxSAVE's own `convertToAssets` returns fxSP shares, not fxUSD.
    @param _shares Amount of fxSAVE to convert
    @return Value of the shares in fxUSD (18 decimals)
    """
    fxsp: uint256 = staticcall FXSAVE.convertToAssets(_shares)
    fxusd: uint256 = 0
    usdc: uint256 = 0
    fxusd, usdc = staticcall FXSP.previewRedeem(fxsp)
    return fxusd + usdc * USDC_SCALE
