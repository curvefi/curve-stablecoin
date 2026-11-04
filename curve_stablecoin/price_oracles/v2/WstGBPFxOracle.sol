// SPDX-License-Identifier: MIT
// Adapted from WsgemFxLlamalendOracle, Copyright (c) 2026 Arb Capital.
// https://github.com/Arb-Capital/wsgem-llamalend/blob/8596dfa09fb94a832017c65dab536a2e480dbc03/src/WsgemFxLlamalendOracle.sol
pragma solidity 0.8.25;

import {IPriceOracle} from "./ChainlinkEMA.sol";

interface IWstGBP {
    function navprice() external view returns (uint256); // Raw NAV; zero means paused.
    function burncost() external view returns (uint256);
    function gem() external view returns (address);
    function decimals() external view returns (uint8);
}

/// @notice USD per wstGBP, scaled by 1e18; crvUSD is $1.
/// @dev NAV pauses hold the redemption rate while FX keeps updating.
contract WstGBPFxOracle is IPriceOracle {
    uint256 private constant WAD = 1e18;
    uint256 public constant MAX_ELAPSED = 7 days; // Maximum growth allowance.
    uint256 public constant MAX_UPSIDE_SPEED = 28_935_185_185; // 0.25% per day

    IWstGBP public immutable WSGEM; // wstGBP wrapper.
    IPriceOracle public immutable CHAINLINK_ADAPTER; // GBP/USD EMA.

    // Redemption rates are 1e18-scaled tGBP per wstGBP.
    uint256 public redemptionRateAnchor; // Positive anchor for the growth cap.
    uint256 public cachedTimestamp; // Last price_w() checkpoint.
    uint256 public cachedRedemptionRate; // Last capped rate, including zero.

    constructor(IWstGBP wrapper, IPriceOracle adapter) {
        WSGEM = wrapper;
        address redemptionToken = wrapper.gem();
        CHAINLINK_ADAPTER = adapter;
        require(redemptionToken != address(0), "invalid wrapper");
        require(wrapper.decimals() == 18 && IWstGBP(redemptionToken).decimals() == 18, "invalid decimals");
        uint256 redemptionRate = _getRedemptionRate();
        require(redemptionRate > 0 && adapter.price() > 0, "unusable initial price");
        redemptionRateAnchor = redemptionRate;
        cachedRedemptionRate = redemptionRate;
        cachedTimestamp = block.timestamp;
    }

    /// @notice Read USD per wstGBP.
    function price() external view returns (uint256) {
        uint256 redemptionRate = _getRedemptionRate();
        if (redemptionRate == 0) return 1;
        redemptionRate = _min(redemptionRate, redemptionRateCeiling());
        uint256 gbpUsdRate = CHAINLINK_ADAPTER.price();
        return _toUsdPrice(redemptionRate, gbpUsdRate);
    }

    /// @notice Return USD per wstGBP and update checkpoints.
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
        // Zero rates preserve the cap anchor.
        cachedTimestamp = block.timestamp;
        cachedRedemptionRate = redemptionRate;
    }

    /// @notice Whether the issuer's NAV reporting is paused.
    function navPaused() external view returns (bool) {
        return WSGEM.navprice() == 0;
    }

    /// @notice Maximum redemption rate allowed by the growth cap.
    function redemptionRateCeiling() public view returns (uint256) {
        uint256 elapsed = _min(block.timestamp - cachedTimestamp, MAX_ELAPSED);
        return redemptionRateAnchor * (WAD + MAX_UPSIDE_SPEED * elapsed) / WAD;
    }

    // Fee-adjusted tGBP per wstGBP; cached during NAV pauses.
    function _getRedemptionRate() private view returns (uint256) {
        if (WSGEM.navprice() == 0) return cachedRedemptionRate;
        return WSGEM.burncost();
    }

    // USD per wstGBP = tGBP per wstGBP * USD per GBP.
    // LlamaLend requires a nonzero price.
    function _toUsdPrice(uint256 redemptionRate, uint256 gbpUsdRate) private pure returns (uint256) {
        uint256 usdPrice = redemptionRate * gbpUsdRate / WAD;
        return usdPrice == 0 ? 1 : usdPrice;
    }

    function _min(uint256 a, uint256 b) private pure returns (uint256) {
        return a < b ? a : b;
    }
}
