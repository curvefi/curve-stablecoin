// SPDX-License-Identifier: MIT
// Adapted from WsgemFxLlamalendOracle, Copyright (c) 2026 Arb Capital.
// https://github.com/Arb-Capital/wsgem-llamalend/blob/8596dfa09fb94a832017c65dab536a2e480dbc03/src/WsgemFxLlamalendOracle.sol
pragma solidity 0.8.25;

import {ChainlinkEMA, IPriceOracle} from "./ChainlinkEMA.sol";

interface IWstGBP {
    function navprice() external view returns (uint256); // Raw NAV; zero means paused.
    function burncost() external view returns (uint256);
    function gem() external view returns (address);
    function decimals() external view returns (uint8);
}

/// @notice USD per wstGBP: capped redemption rate times smoothed GBP/USD. crvUSD is $1.
/// @dev Hold the redemption rate on a NAV pause; FX continues. Contract-call failures revert normally.
contract WstGBPFxOracle is IPriceOracle {
    uint256 private constant WAD = 1e18; // 18-decimal price scale: 1e18 represents one unit.
    uint256 public constant MAX_ELAPSED = 7 days; // Maximum time credited to redemption-rate growth.
    uint256 public constant MAX_UPSIDE_SPEED = 28_935_185_185; // 0.25% per day

    // These addresses are readable by anyone (public) and fixed at deployment (immutable).
    IWstGBP public immutable WSGEM; // wstGBP collateral wrapper.
    ChainlinkEMA public immutable CHAINLINK_ADAPTER; // Curve's stateful EMA adapter over the GBP/USD feed.

    uint256 public redemptionRateAnchor; // Positive redemption rate used by the upside cap, scaled by 1e18.
    uint256 public cachedTimestamp; // Last price_w() checkpoint time, in Unix seconds.
    uint256 public cachedRedemptionRate; // Last capped tGBP per wstGBP, including zero, scaled by 1e18.

    /// @notice Configure the wrapper and Chainlink EMA adapter and initialize the price.
    constructor(IWstGBP wrapper, ChainlinkEMA adapter) {
        WSGEM = wrapper;
        address redemptionToken = wrapper.gem();
        CHAINLINK_ADAPTER = adapter;
        require(redemptionToken != address(0), "invalid wrapper");
        require(wrapper.decimals() == 18 && IWstGBP(redemptionToken).decimals() == 18, "invalid decimals");
        require(adapter.OBSERVATIONS() == 20 && adapter.INTERVAL() == 30, "invalid EMA");
        uint256 redemptionRate = _getRedemptionRate();
        require(redemptionRate > 0 && adapter.price() > 0, "unusable initial price");
        redemptionRateAnchor = redemptionRate;
        cachedRedemptionRate = redemptionRate;
        cachedTimestamp = block.timestamp;
    }

    /// @notice Read USD per wstGBP, scaled by 1e18, without updating checkpoints.
    function price() external view returns (uint256) {
        uint256 redemptionRate = _getRedemptionRate();
        if (redemptionRate == 0) return 1;
        redemptionRate = _min(redemptionRate, redemptionRateCeiling());
        uint256 gbpUsdRate = CHAINLINK_ADAPTER.price();
        return _toUsdPrice(redemptionRate, gbpUsdRate);
    }

    /// @notice Return USD per wstGBP, scaled by 1e18, and save the pricing checkpoints.
    // EMA state lives in its adapter; the redemption-rate cap and cache live here.
    function price_w() external returns (uint256 usdPrice) {
        uint256 redemptionRate = _getRedemptionRate();
        if (redemptionRate == 0) {
            usdPrice = 1;
        } else {
            redemptionRate = _min(redemptionRate, redemptionRateCeiling());
            uint256 gbpUsdRate = CHAINLINK_ADAPTER.price_w();
            usdPrice = _toUsdPrice(redemptionRate, gbpUsdRate);
            redemptionRateAnchor = redemptionRate;
        }
        // Each checkpoint resets the cap clock; a zero redemption rate preserves the anchor.
        cachedTimestamp = block.timestamp;
        cachedRedemptionRate = redemptionRate;
    }

    /// @notice Whether NAV reporting is paused and the cached redemption rate is used.
    function navPaused() external view returns (bool) {
        return WSGEM.navprice() == 0;
    }

    /// @notice Maximum redemption rate in tGBP per wstGBP allowed by the cap, scaled by 1e18.
    function redemptionRateCeiling() public view returns (uint256) {
        uint256 elapsed = _min(block.timestamp - cachedTimestamp, MAX_ELAPSED);
        return redemptionRateAnchor * (WAD + MAX_UPSIDE_SPEED * elapsed) / WAD;
    }

    // Read tGBP per wstGBP after redemption fees, or reuse the cached rate during a NAV pause.
    function _getRedemptionRate() private view returns (uint256) {
        if (WSGEM.navprice() == 0) return cachedRedemptionRate;
        return WSGEM.burncost();
    }

    // USD per wstGBP = tGBP per wstGBP * USD per GBP; divide by WAD to keep 18 decimals.
    // Floor at one wei so the oracle never returns zero.
    function _toUsdPrice(uint256 redemptionRate, uint256 gbpUsdRate) private pure returns (uint256) {
        uint256 usdPrice = redemptionRate * gbpUsdRate / WAD;
        return usdPrice == 0 ? 1 : usdPrice;
    }

    function _min(uint256 a, uint256 b) private pure returns (uint256) {
        return a < b ? a : b;
    }
}
