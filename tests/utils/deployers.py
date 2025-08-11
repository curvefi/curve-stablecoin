"""
Centralized deployers for all contracts used in tests.
Each deployer is a VyperDeployer object returned using boa.load_partial().
"""

import boa

# Compiler args if needed
compiler_args = {}

# Contract paths
BASE_CONTRACT_PATH = "contracts/"
TESTING_CONTRACT_PATH = "contracts/testing/"
LENDING_CONTRACT_PATH = "contracts/lending/"
MPOLICIES_CONTRACT_PATH = "contracts/mpolicies/"
PRICE_ORACLES_CONTRACT_PATH = "contracts/price_oracles/"
STABILIZER_CONTRACT_PATH = "contracts/stabilizer/"
FLASHLOAN_CONTRACT_PATH = "contracts/flashloan/"
STABLESWAP_NG_PATH = "contracts/testing/stableswap-ng/contracts/main/"

# Core contracts
AMM_DEPLOYER = boa.load_partial(BASE_CONTRACT_PATH + "AMM.vy", compiler_args=compiler_args)
CONTROLLER_DEPLOYER = boa.load_partial(BASE_CONTRACT_PATH + "Controller.vy", compiler_args=compiler_args)
CONTROLLER_FACTORY_DEPLOYER = boa.load_partial(BASE_CONTRACT_PATH + "ControllerFactory.vy", compiler_args=compiler_args)
STABLECOIN_DEPLOYER = boa.load_partial(BASE_CONTRACT_PATH + "Stablecoin.vy", compiler_args=compiler_args)
STABLESWAP_DEPLOYER = boa.load_partial(BASE_CONTRACT_PATH + "Stableswap.vy", compiler_args=compiler_args)

# Lending contracts
VAULT_DEPLOYER = boa.load_partial(LENDING_CONTRACT_PATH + "Vault.vy", compiler_args=compiler_args)
LL_CONTROLLER_DEPLOYER = boa.load_partial(LENDING_CONTRACT_PATH + "LLController.vy", compiler_args=compiler_args)
LENDING_FACTORY_DEPLOYER = boa.load_partial(LENDING_CONTRACT_PATH + "LendingFactory.vy", compiler_args=compiler_args)

# Flashloan contracts
FLASH_LENDER_DEPLOYER = boa.load_partial(FLASHLOAN_CONTRACT_PATH + "FlashLender.vy", compiler_args=compiler_args)

# Monetary policies
CONSTANT_MONETARY_POLICY_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "ConstantMonetaryPolicy.vy", compiler_args=compiler_args)
SEMILOG_MONETARY_POLICY_DEPLOYER = boa.load_partial(MPOLICIES_CONTRACT_PATH + "SemilogMonetaryPolicy.vy", compiler_args=compiler_args)
SECONDARY_MONETARY_POLICY_DEPLOYER = boa.load_partial(MPOLICIES_CONTRACT_PATH + "SecondaryMonetaryPolicy.vy", compiler_args=compiler_args)
AGG_MONETARY_POLICY2_DEPLOYER = boa.load_partial(MPOLICIES_CONTRACT_PATH + "AggMonetaryPolicy2.vy", compiler_args=compiler_args)
AGG_MONETARY_POLICY3_DEPLOYER = boa.load_partial(MPOLICIES_CONTRACT_PATH + "AggMonetaryPolicy3.vy", compiler_args=compiler_args)

# Price oracles
DUMMY_PRICE_ORACLE_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "DummyPriceOracle.vy", compiler_args=compiler_args)
CRYPTO_FROM_POOL_DEPLOYER = boa.load_partial(PRICE_ORACLES_CONTRACT_PATH + "CryptoFromPool.vy", compiler_args=compiler_args)
EMA_PRICE_ORACLE_DEPLOYER = boa.load_partial(PRICE_ORACLES_CONTRACT_PATH + "EmaPriceOracle.vy", compiler_args=compiler_args)
AGGREGATE_STABLE_PRICE3_DEPLOYER = boa.load_partial(PRICE_ORACLES_CONTRACT_PATH + "AggregateStablePrice3.vy", compiler_args=compiler_args)
CRYPTO_WITH_STABLE_PRICE_DEPLOYER = boa.load_partial(PRICE_ORACLES_CONTRACT_PATH + "CryptoWithStablePrice.vy", compiler_args=compiler_args)
CRYPTO_WITH_STABLE_PRICE_AND_CHAINLINK_DEPLOYER = boa.load_partial(PRICE_ORACLES_CONTRACT_PATH + "CryptoWithStablePriceAndChainlink.vy", compiler_args=compiler_args)

# Proxy oracle contracts
PROXY_ORACLE_DEPLOYER = boa.load_partial(PRICE_ORACLES_CONTRACT_PATH + "proxy/ProxyOracle.vy", compiler_args=compiler_args)
PROXY_ORACLE_FACTORY_DEPLOYER = boa.load_partial(PRICE_ORACLES_CONTRACT_PATH + "proxy/ProxyOracleFactory.vy", compiler_args=compiler_args)

# LP oracle contracts
LP_ORACLE_STABLE_DEPLOYER = boa.load_partial(PRICE_ORACLES_CONTRACT_PATH + "lp-oracles/LPOracleStable.vy", compiler_args=compiler_args)
LP_ORACLE_CRYPTO_DEPLOYER = boa.load_partial(PRICE_ORACLES_CONTRACT_PATH + "lp-oracles/LPOracleCrypto.vy", compiler_args=compiler_args)
LP_ORACLE_FACTORY_DEPLOYER = boa.load_partial(PRICE_ORACLES_CONTRACT_PATH + "lp-oracles/LPOracleFactory.vy", compiler_args=compiler_args)

# Stabilizer contracts
PEG_KEEPER_V2_DEPLOYER = boa.load_partial(STABILIZER_CONTRACT_PATH + "PegKeeperV2.vy", compiler_args=compiler_args)
PEG_KEEPER_REGULATOR_DEPLOYER = boa.load_partial(STABILIZER_CONTRACT_PATH + "PegKeeperRegulator.vy", compiler_args=compiler_args)

# Callback contracts
LM_CALLBACK_DEPLOYER = boa.load_partial(BASE_CONTRACT_PATH + "LMCallback.vy", compiler_args=compiler_args)
BOOSTED_LM_CALLBACK_DEPLOYER = boa.load_partial(BASE_CONTRACT_PATH + "BoostedLMCallback.vy", compiler_args=compiler_args)

# Testing/Mock contracts
ERC20_MOCK_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "ERC20Mock.vy", compiler_args=compiler_args)
ERC20_CRV_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "ERC20CRV.vy", compiler_args=compiler_args)
WETH_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "WETH.vy", compiler_args=compiler_args)
VOTING_ESCROW_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "VotingEscrow.vy", compiler_args=compiler_args)
VE_DELEGATION_MOCK_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "VEDelegationMock.vy", compiler_args=compiler_args)
GAUGE_CONTROLLER_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "GaugeController.vy", compiler_args=compiler_args)
MINTER_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "Minter.vy", compiler_args=compiler_args)
FAKE_LEVERAGE_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "FakeLeverage.vy", compiler_args=compiler_args)
BLOCK_COUNTER_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "BlockCounter.vy", compiler_args=compiler_args)
DUMMY_FLASH_BORROWER_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "DummyFlashBorrower.vy", compiler_args=compiler_args)
DUMMY_LM_CALLBACK_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "DummyLMCallback.vy", compiler_args=compiler_args)
LM_CALLBACK_WITH_REVERTS_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "LMCallbackWithReverts.vy", compiler_args=compiler_args)
MOCK_FACTORY_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "MockFactory.vy", compiler_args=compiler_args)
MOCK_MARKET_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "MockMarket.vy", compiler_args=compiler_args)
MOCK_RATE_SETTER_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "MockRateSetter.vy", compiler_args=compiler_args)
MOCK_PEG_KEEPER_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "MockPegKeeper.vy", compiler_args=compiler_args)
MOCK_RATE_ORACLE_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "MockRateOracle.vy", compiler_args=compiler_args)
CHAINLINK_AGGREGATOR_MOCK_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "ChainlinkAggregatorMock.vy", compiler_args=compiler_args)
TRICRYPTO_MOCK_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "TricryptoMock.vy", compiler_args=compiler_args)
MOCK_SWAP2_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "MockSwap2.vy", compiler_args=compiler_args)
MOCK_SWAP3_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "MockSwap3.vy", compiler_args=compiler_args)
SWAP_FACTORY_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "SwapFactory.vy", compiler_args=compiler_args)
OPTIMIZE_MATH_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "OptimizeMath.vy", compiler_args=compiler_args)
TEST_PACKING_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "TestPacking.vy", compiler_args=compiler_args)
OLD_AMM_DEPLOYER = boa.load_partial(TESTING_CONTRACT_PATH + "OldAMM.vy", compiler_args=compiler_args)

# LP oracle testing contracts
MOCK_STABLE_SWAP_DEPLOYER = boa.load_partial(PRICE_ORACLES_CONTRACT_PATH + "lp-oracles/testing/MockStableSwap.vy", compiler_args=compiler_args)
MOCK_CRYPTO_SWAP_DEPLOYER = boa.load_partial(PRICE_ORACLES_CONTRACT_PATH + "lp-oracles/testing/MockCryptoSwap.vy", compiler_args=compiler_args)
MOCK_STABLE_SWAP_NO_ARGUMENT_DEPLOYER = boa.load_partial(PRICE_ORACLES_CONTRACT_PATH + "lp-oracles/testing/MockStableSwapNoArgument.vy", compiler_args=compiler_args)

# Stableswap NG contracts
CURVE_STABLESWAP_FACTORY_NG_DEPLOYER = boa.load_partial(STABLESWAP_NG_PATH + "CurveStableSwapFactoryNG.vy", compiler_args=compiler_args)
CURVE_STABLESWAP_NG_DEPLOYER = boa.load_partial(STABLESWAP_NG_PATH + "CurveStableSwapNG.vy", compiler_args=compiler_args)
CURVE_STABLESWAP_NG_MATH_DEPLOYER = boa.load_partial(STABLESWAP_NG_PATH + "CurveStableSwapNGMath.vy", compiler_args=compiler_args)
CURVE_STABLESWAP_NG_VIEWS_DEPLOYER = boa.load_partial(STABLESWAP_NG_PATH + "CurveStableSwapNGViews.vy", compiler_args=compiler_args)