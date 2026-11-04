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

/// @notice USD per wstGBP: capped redemption NAV times smoothed GBP/USD. crvUSD is $1.
/// @dev Hold the last NAV on a pause; FX pricing continues. Contract-call failures revert normally.
contract WstGBPFxOracle is IPriceOracle {
    uint256 private constant WAD = 1e18; // 18-decimal price scale: 1e18 represents one unit.
    uint256 public constant MAX_ELAPSED = 7 days; // Maximum time credited to NAV growth.
    uint256 public constant MAX_UPSIDE_SPEED = 28_935_185_185; // 0.25% per day

    // These addresses are readable by anyone (public) and fixed at deployment (immutable).
    IWstGBP public immutable WSGEM; // wstGBP collateral wrapper.
    ChainlinkEMA public immutable CHAINLINK_ADAPTER; // Curve's stateful EMA adapter over the GBP/USD feed.

    uint256 public cachedQuote; // Positive NAV anchor for the upside cap, scaled by 1e18.
    uint256 public cachedTimestamp; // Last price_w() checkpoint time, in Unix seconds.
    uint256 public cachedNav; // Last reported capped NAV in tGBP, including a live zero quote.

    /// @notice Configure the wrapper and Chainlink EMA adapter and initialize the price.
    constructor(IWstGBP wrapper, ChainlinkEMA adapter) {
        WSGEM = wrapper;
        address redemptionToken = wrapper.gem();
        CHAINLINK_ADAPTER = adapter;
        require(redemptionToken != address(0), "invalid wrapper");
        require(wrapper.decimals() == 18 && IWstGBP(redemptionToken).decimals() == 18, "invalid decimals");
        require(adapter.OBSERVATIONS() == 20 && adapter.INTERVAL() == 30, "invalid EMA");
        uint256 quote = _getNav();
        require(quote > 0 && adapter.price() > 0, "unusable initial price");
        cachedQuote = quote;
        cachedNav = quote;
        cachedTimestamp = block.timestamp;
    }

    /// @notice Read USD per wstGBP, scaled by 1e18, without updating checkpoints.
    function price() external view returns (uint256) {
        uint256 quote = _getNav();
        if (quote == 0) return 1;
        quote = _min(quote, quoteCeiling());
        uint256 conversionRate = CHAINLINK_ADAPTER.price();
        return _toUsdPrice(quote, conversionRate);
    }

    /// @notice Return USD per wstGBP, scaled by 1e18, and save the pricing checkpoints.
    // EMA state lives in its adapter; the NAV cap and last NAV live here.
    function price_w() external returns (uint256 result) {
        uint256 quote = _getNav();
        if (quote == 0) {
            result = 1;
        } else {
            quote = _min(quote, quoteCeiling());
            uint256 conversionRate = CHAINLINK_ADAPTER.price_w();
            result = _toUsdPrice(quote, conversionRate);
            cachedQuote = quote;
        }
        // Each checkpoint resets the cap clock; a zero quote leaves its NAV anchor intact.
        cachedTimestamp = block.timestamp;
        cachedNav = quote;
    }

    /// @notice Whether NAV reporting is paused and the cached NAV is used.
    function navPaused() external view returns (bool) {
        return WSGEM.navprice() == 0;
    }

    /// @notice Maximum NAV in GBP per wstGBP allowed by the upside cap, scaled by 1e18.
    function quoteCeiling() public view returns (uint256) {
        uint256 elapsed = _min(block.timestamp - cachedTimestamp, MAX_ELAPSED);
        return cachedQuote * (WAD + MAX_UPSIDE_SPEED * elapsed) / WAD;
    }

    // Read fee-adjusted NAV, or reuse the last reported NAV while paused.
    function _getNav() private view returns (uint256) {
        if (WSGEM.navprice() == 0) return cachedNav;
        return WSGEM.burncost();
    }

    // USD per wstGBP = GBP NAV * GBP/USD; divide by WAD to keep 18 decimals.
    // Floor at one wei so the oracle never returns zero.
    function _toUsdPrice(uint256 quote, uint256 conversionRate) private pure returns (uint256) {
        uint256 result = quote * conversionRate / WAD;
        return result == 0 ? 1 : result;
    }

    function _min(uint256 a, uint256 b) private pure returns (uint256) {
        return a < b ? a : b;
    }
}
