// SPDX-License-Identifier: MIT
// Adapted from WsgemFxLlamalendOracle, Copyright (c) 2026 Arb Capital.
// https://github.com/Arb-Capital/wsgem-llamalend/blob/8596dfa09fb94a832017c65dab536a2e480dbc03/src/WsgemFxLlamalendOracle.sol
pragma solidity 0.8.25;

import {IPriceOracle} from "./ChainlinkEMA.sol";

interface IWstGBP {
    function navprice() external view returns (uint256); // Raw NAV; zero means paused.
    function act() external view returns (IWstGBPFees);
    function gem() external view returns (address);
    function decimals() external view returns (uint8);
}

interface IWstGBPFees {
    function burncost(uint256 nav) external view returns (uint256);
}

/// @notice USD per wstGBP, scaled by 1e18; crvUSD is $1.
/// @dev Only NAV growth is capped; fees apply afterwards. NAV pauses hold the net rate while FX updates.
contract WstGBPFxOracle is IPriceOracle {
    uint256 private constant WAD = 1e18;
    uint256 public constant MAX_ELAPSED = 7 days; // Maximum growth allowance.
    uint256 public constant MAX_UPSIDE_SPEED = 28_935_185_185; // 0.25% per day

    IWstGBP public immutable WSGEM; // wstGBP wrapper.
    IPriceOracle public immutable CHAINLINK_ADAPTER; // GBP/USD EMA.

    // NAV and redemption rates are 1e18-scaled tGBP per wstGBP.
    uint256 public navAnchor; // Capped NAV before redemption fees.
    uint256 public cachedTimestamp; // Last price_w() checkpoint.
    uint256 public cachedRedemptionRate; // Last net redemption rate, including zero.

    constructor(IWstGBP wrapper, IPriceOracle adapter) {
        WSGEM = wrapper;
        address redemptionToken = wrapper.gem();
        CHAINLINK_ADAPTER = adapter;
        require(redemptionToken != address(0), "invalid wrapper");
        require(wrapper.decimals() == 18 && IWstGBP(redemptionToken).decimals() == 18, "invalid decimals");
        uint256 nav = wrapper.navprice();
        require(nav > 0, "unusable initial price");
        uint256 redemptionRate = wrapper.act().burncost(nav);
        require(redemptionRate > 0 && adapter.price() > 0, "unusable initial price");
        navAnchor = nav;
        cachedRedemptionRate = redemptionRate;
        cachedTimestamp = block.timestamp;
    }

    /// @notice Read USD per wstGBP.
    function price() external view returns (uint256) {
        (, uint256 redemptionRate) = _getRates();
        if (redemptionRate == 0) return 1;
        uint256 gbpUsdRate = CHAINLINK_ADAPTER.price();
        return _toUsdPrice(redemptionRate, gbpUsdRate);
    }

    /// @notice Return USD per wstGBP and update checkpoints.
    function price_w() external returns (uint256 usdPrice) {
        (uint256 nav, uint256 redemptionRate) = _getRates();
        if (redemptionRate == 0) {
            usdPrice = 1;
        } else {
            uint256 gbpUsdRate = CHAINLINK_ADAPTER.price_w();
            usdPrice = _toUsdPrice(redemptionRate, gbpUsdRate);
        }
        // A 100% fee must not hide NAV changes; a NAV pause preserves the anchor.
        if (nav > 0) navAnchor = nav;
        cachedTimestamp = block.timestamp;
        cachedRedemptionRate = redemptionRate;
    }

    /// @notice Whether the issuer's NAV reporting is paused.
    function navPaused() external view returns (bool) {
        return WSGEM.navprice() == 0;
    }

    /// @notice Maximum pre-fee NAV allowed by the growth cap.
    function navCeiling() public view returns (uint256) {
        uint256 elapsed = _min(block.timestamp - cachedTimestamp, MAX_ELAPSED);
        return navAnchor * (WAD + MAX_UPSIDE_SPEED * elapsed) / WAD;
    }

    // Apply the wrapper's own fee calculation to capped NAV, including its rounding.
    function _getRates() private view returns (uint256 nav, uint256 redemptionRate) {
        nav = WSGEM.navprice();
        if (nav == 0) return (0, cachedRedemptionRate);
        nav = _min(nav, navCeiling());
        redemptionRate = WSGEM.act().burncost(nav);
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
