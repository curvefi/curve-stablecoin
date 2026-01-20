// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import {Script, console} from "forge-std/Script.sol";

/**
 * @title AggMonetaryPolicy4 Deployment Script
 * @notice Deploys the AggMonetaryPolicy4 Vyper contract using Foundry
 * @dev This script uses deployCode to deploy Vyper contracts with hardcoded parameters
 *
 * Deployment Parameters:
 * - Admin: 0x40907540d8a6C65c637785e8f8B742ae6b0b9968
 * - Price Oracle: 0x18672b1b0c623a30089A280Ed9256379fb0E4E62
 * - Controller Factory: 0xC9332fdCB1C491Dcc683bAe86Fe3cb70360738BC
 * - Rate: 3662480974 (~12.24% APR base rate)
 * - Sigma: 7e15 (0.7%)
 * - Target Debt Fraction: ~26.67%
 * - Debt Ratio EMA Time: 9 days
 */
contract DeployAggMonetaryPolicy4 is Script {
    // Hardcoded deployment parameters
    address constant ADMIN = 0x40907540d8a6C65c637785e8f8B742ae6b0b9968;
    address constant PRICE_ORACLE = 0x18672b1b0c623a30089A280Ed9256379fb0E4E62;
    address constant CONTROLLER_FACTORY = 0xC9332fdCB1C491Dcc683bAe86Fe3cb70360738BC;

    // PegKeepers
    address constant PEG_KEEPER_0 = 0x9201da0D97CaAAff53f01B2fB56767C7072dE340;
    address constant PEG_KEEPER_1 = 0xFb726F57d251aB5C731E5C64eD4F5F94351eF9F3;
    address constant PEG_KEEPER_2 = 0x3fA20eAa107DE08B38a8734063D605d5842fe09C;
    address constant PEG_KEEPER_3 = 0x338Cb2D827112d989A861cDe87CD9FfD913A1f9D;
    address constant PEG_KEEPER_4 = address(0); // empty(address)

    // Monetary Policy Parameters
    uint256 constant RATE = 3662480974;                      // ~12.24% APR base rate
    int256 constant SIGMA = 7000000000000000;                // 7e15 (0.7%)
    uint256 constant TARGET_DEBT_FRACTION = 266700000000000000; // ~26.67%
    uint256 constant EXTRA_CONST = 475646879;
    uint256 constant DEBT_RATIO_EMA_TIME = 777600;           // 9 days (9 * 86400)

    function run() public returns (address) {
        console.log("=== AggMonetaryPolicy4 Deployment ===");
        console.log("");

        // Build pegKeepers array
        address[5] memory pegKeepers = [
            PEG_KEEPER_0,
            PEG_KEEPER_1,
            PEG_KEEPER_2,
            PEG_KEEPER_3,
            PEG_KEEPER_4
        ];

        // Log all parameters
        console.log("Admin:", ADMIN);
        console.log("Price Oracle:", PRICE_ORACLE);
        console.log("Controller Factory:", CONTROLLER_FACTORY);
        console.log("");
        console.log("PegKeepers:");
        console.log("  [0]:", pegKeepers[0]);
        console.log("  [1]:", pegKeepers[1]);
        console.log("  [2]:", pegKeepers[2]);
        console.log("  [3]:", pegKeepers[3]);
        console.log("  [4]:", pegKeepers[4]);
        console.log("");
        console.log("Rate:", RATE, "(~12.24% APR)");
        console.log("Sigma:", uint256(SIGMA), "(0.7%)");
        console.log("Target Debt Fraction:", TARGET_DEBT_FRACTION, "(~26.67%)");
        console.log("Extra Const:", EXTRA_CONST);
        console.log("Debt Ratio EMA Time:", DEBT_RATIO_EMA_TIME, "(9 days)");
        console.log("");

        // Get deployer private key from environment
        uint256 deployerPrivateKey = vm.envUint("PRIVATE_KEY");
        address deployer = vm.addr(deployerPrivateKey);
        console.log("Deployer:", deployer);
        console.log("Deployer balance:", deployer.balance);
        console.log("");

        // Start broadcasting transactions
        vm.startBroadcast(deployerPrivateKey);

        // Deploy Vyper contract using deployCode
        address deployedContract = deployCode(
            "curve_stablecoin/mpolicies/AggMonetaryPolicy4.vy",
            abi.encode(
                ADMIN,
                PRICE_ORACLE,
                CONTROLLER_FACTORY,
                pegKeepers,
                RATE,
                SIGMA,
                TARGET_DEBT_FRACTION,
                EXTRA_CONST,
                DEBT_RATIO_EMA_TIME
            )
        );

        vm.stopBroadcast();

        console.log("=== Deployment Successful ===");
        console.log("AggMonetaryPolicy4 deployed at:", deployedContract);
        console.log("");
        console.log("Next steps:");
        console.log("1. Verify the deployment parameters");
        console.log("2. Update the following controllers to use this monetary policy:");
        console.log("   - 0x100dAa78fC509Db39Ef7D04DE0c1ABD299f4C6CE (wstETH)");
        console.log("   - 0x4e59541306910aD6dC1daC0AC9dFB29bD9F15c67 (WBTC)");
        console.log("   - 0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635 (WETH)");
        console.log("   - 0xEC0820EfafC41D8943EE8dE495fC9Ba8495B15cf (sfrxETH2)");
        console.log("   - 0x1C91da0223c763d2e0173243eAdaA0A2ea47E704 (tBTC)");
        console.log("   - 0x652aEa6B22310C89DCc506710CaD24d2Dba56B11 (weETH)");
        console.log("   - 0xf8C786b1064889fFd3c8A08B48D5e0c159F4cBe3 (cbBTC)");
        console.log("   - 0x8aca5A776a878Ea1F8967e70a23b8563008f58Ef (LBTC)");

        return deployedContract;
    }
}
