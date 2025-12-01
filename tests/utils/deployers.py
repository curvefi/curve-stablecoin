"""
Centralized deployers for all contracts used in tests.
Each deployer is a VyperDeployer object returned using boa.load_partial().
"""

import boa
from vyper.compiler.settings import OptimizationLevel

# Base compiler args
compiler_args_default = {"experimental_codegen": False}

# Compiler args for different optimization levels
# Contracts with #pragma optimize codesize
compiler_args_codesize = {
    **compiler_args_default,
    "optimize": OptimizationLevel.CODESIZE,
}

# Contracts with #pragma optimize gas
compiler_args_gas = {**compiler_args_default, "optimize": OptimizationLevel.GAS}

# Contract paths
BASE_CONTRACT_PATH = "curve_stablecoin/"
TESTING_CONTRACT_PATH = "curve_stablecoin/testing/"
LENDING_CONTRACT_PATH = "curve_stablecoin/lending/"
MPOLICIES_CONTRACT_PATH = "curve_stablecoin/mpolicies/"
PRICE_ORACLES_CONTRACT_PATH = "curve_stablecoin/price_oracles/"
STABILIZER_CONTRACT_PATH = "curve_stablecoin/stabilizer/"
FLASHLOAN_CONTRACT_PATH = "curve_stablecoin/flashloan/"
STABLESWAP_NG_PATH = "curve_stablecoin/testing/stableswap-ng/curve_stablecoin/main/"
ZAPS_CONTRACT_PATH = "curve_stablecoin/zaps/"

# Constants contract (for accessing constants)
CONSTANTS_DEPLOYER = boa.load_partial(
    BASE_CONTRACT_PATH + "constants.vy", compiler_args=compiler_args_default
)

# Core contracts
AMM_DEPLOYER = boa.load_partial(
    BASE_CONTRACT_PATH + "AMM.vy", compiler_args=compiler_args_default
)
CONTROLLER_DEPLOYER = boa.load_partial(
    BASE_CONTRACT_PATH + "Controller.vy", compiler_args=compiler_args_codesize
)
CONTROLLER_VIEW_DEPLOYER = boa.load_partial(
    BASE_CONTRACT_PATH + "ControllerView.vy", compiler_args=compiler_args_codesize
)
MINT_CONTROLLER_DEPLOYER = boa.load_partial(
    BASE_CONTRACT_PATH + "MintController.vy", compiler_args=compiler_args_codesize
)
CONTROLLER_FACTORY_DEPLOYER = boa.load_partial(
    BASE_CONTRACT_PATH + "ControllerFactory.vy", compiler_args=compiler_args_default
)
STABLECOIN_DEPLOYER = boa.load_partial(
    BASE_CONTRACT_PATH + "Stablecoin.vy", compiler_args=compiler_args_default
)
STABLESWAP_DEPLOYER = boa.load_partial(
    BASE_CONTRACT_PATH + "Stableswap.vy", compiler_args=compiler_args_default
)

# Lending contracts - all have #pragma optimize codesize
VAULT_DEPLOYER = boa.load_partial(
    LENDING_CONTRACT_PATH + "Vault.vy", compiler_args=compiler_args_codesize
)
LEND_CONTROLLER_DEPLOYER = boa.load_partial(
    LENDING_CONTRACT_PATH + "LendController.vy", compiler_args=compiler_args_codesize
)
LEND_CONTROLLER_VIEW_DEPLOYER = boa.load_partial(
    LENDING_CONTRACT_PATH + "LendControllerView.vy", compiler_args=compiler_args_default
)
LENDING_FACTORY_DEPLOYER = boa.load_partial(
    LENDING_CONTRACT_PATH + "LendFactory.vy", compiler_args=compiler_args_codesize
)

# Flashloan contracts
FLASH_LENDER_DEPLOYER = boa.load_partial(
    FLASHLOAN_CONTRACT_PATH + "FlashLender.vy", compiler_args=compiler_args_default
)

# Zap contracts
PARTIAL_REPAY_ZAP_DEPLOYER = boa.load_partial(
    ZAPS_CONTRACT_PATH + "PartialRepayZap.vy", compiler_args=compiler_args_default
)
PARTIAL_REPAY_ZAP_CALLBACK_DEPLOYER = boa.load_partial(
    ZAPS_CONTRACT_PATH + "PartialRepayZapCallback.vy",
    compiler_args=compiler_args_default,
)

# Monetary policies - all have no pragma
CONSTANT_MONETARY_POLICY_DEPLOYER = boa.load_partial(
    TESTING_CONTRACT_PATH + "ConstantMonetaryPolicy.vy",
    compiler_args=compiler_args_default,
)
CONSTANT_MONETARY_POLICY_LENDING_DEPLOYER = boa.load_partial(
    TESTING_CONTRACT_PATH + "ConstantMonetaryPolicyLending.vy",
    compiler_args=compiler_args_default,
)
SEMILOG_MONETARY_POLICY_DEPLOYER = boa.load_partial(
    MPOLICIES_CONTRACT_PATH + "SemilogMonetaryPolicy.vy",
    compiler_args=compiler_args_default,
)
SECONDARY_MONETARY_POLICY_DEPLOYER = boa.load_partial(
    MPOLICIES_CONTRACT_PATH + "SecondaryMonetaryPolicy.vy",
    compiler_args=compiler_args_default,
)
AGG_MONETARY_POLICY2_DEPLOYER = boa.load_partial(
    MPOLICIES_CONTRACT_PATH + "AggMonetaryPolicy2.vy",
    compiler_args=compiler_args_default,
)
AGG_MONETARY_POLICY3_DEPLOYER = boa.load_partial(
    MPOLICIES_CONTRACT_PATH + "AggMonetaryPolicy3.vy",
    compiler_args=compiler_args_default,
)

# Price oracles
DUMMY_PRICE_ORACLE_DEPLOYER = boa.load_partial(
    TESTING_CONTRACT_PATH + "DummyPriceOracle.vy", compiler_args=compiler_args_default
)
CRYPTO_FROM_POOL_DEPLOYER = boa.load_partial(
    PRICE_ORACLES_CONTRACT_PATH + "CryptoFromPool.vy",
    compiler_args=compiler_args_default,
)
EMA_PRICE_ORACLE_DEPLOYER = boa.load_partial(
    PRICE_ORACLES_CONTRACT_PATH + "EmaPriceOracle.vy",
    compiler_args=compiler_args_default,
)
AGGREGATE_STABLE_PRICE3_DEPLOYER = boa.load_partial(
    PRICE_ORACLES_CONTRACT_PATH + "AggregateStablePrice3.vy",
    compiler_args=compiler_args_default,
)
CRYPTO_WITH_STABLE_PRICE_DEPLOYER = boa.load_partial(
    PRICE_ORACLES_CONTRACT_PATH + "CryptoWithStablePrice.vy",
    compiler_args=compiler_args_default,
)
CRYPTO_WITH_STABLE_PRICE_AND_CHAINLINK_DEPLOYER = boa.load_partial(
    PRICE_ORACLES_CONTRACT_PATH + "CryptoWithStablePriceAndChainlink.vy",
    compiler_args=compiler_args_default,
)

# Proxy oracle contracts - have #pragma optimize gas
PROXY_ORACLE_DEPLOYER = boa.load_partial(
    PRICE_ORACLES_CONTRACT_PATH + "proxy/ProxyOracle.vy",
    compiler_args=compiler_args_gas,
)
PROXY_ORACLE_FACTORY_DEPLOYER = boa.load_partial(
    PRICE_ORACLES_CONTRACT_PATH + "proxy/ProxyOracleFactory.vy",
    compiler_args=compiler_args_gas,
)

# LP oracle contracts
LP_ORACLE_STABLE_DEPLOYER = boa.load_partial(
    PRICE_ORACLES_CONTRACT_PATH + "lp-oracles/LPOracleStable.vy",
    compiler_args=compiler_args_default,
)
LP_ORACLE_CRYPTO_DEPLOYER = boa.load_partial(
    PRICE_ORACLES_CONTRACT_PATH + "lp-oracles/LPOracleCrypto.vy",
    compiler_args=compiler_args_default,
)
# LPOracleFactory.vy has #pragma optimize gas
LP_ORACLE_FACTORY_DEPLOYER = boa.load_partial(
    PRICE_ORACLES_CONTRACT_PATH + "lp-oracles/LPOracleFactory.vy",
    compiler_args=compiler_args_gas,
)

# Stabilizer contracts
PEG_KEEPER_V2_DEPLOYER = boa.load_partial(
    STABILIZER_CONTRACT_PATH + "PegKeeperV2.vy", compiler_args=compiler_args_default
)
PEG_KEEPER_REGULATOR_DEPLOYER = boa.load_partial(
    STABILIZER_CONTRACT_PATH + "PegKeeperRegulator.vy",
    compiler_args=compiler_args_default,
)
PEG_KEEPER_OFFBOARDING_DEPLOYER = boa.load_partial(
    STABILIZER_CONTRACT_PATH + "PegKeeperOffboarding.vy",
    compiler_args=compiler_args_default,
)

# Callback contracts
LM_CALLBACK_DEPLOYER = boa.load_partial(
    BASE_CONTRACT_PATH + "LMCallback.vy", compiler_args=compiler_args_default
)

# Testing/Mock contracts
ERC20_MOCK_DEPLOYER = boa.load_partial(
    TESTING_CONTRACT_PATH + "ERC20Mock.vy", compiler_args=compiler_args_default
)
ERC20_CRV_DEPLOYER = boa.load_partial(
    TESTING_CONTRACT_PATH + "ERC20CRV.vy", compiler_args=compiler_args_default
)
WETH_DEPLOYER = boa.load_partial(
    TESTING_CONTRACT_PATH + "WETH.vy", compiler_args=compiler_args_default
)
VOTING_ESCROW_DEPLOYER = boa.load_partial(
    TESTING_CONTRACT_PATH + "VotingEscrow.vy", compiler_args=compiler_args_default
)
GAUGE_CONTROLLER_DEPLOYER = boa.load_partial(
    TESTING_CONTRACT_PATH + "GaugeController.vy", compiler_args=compiler_args_default
)
MINTER_DEPLOYER = boa.load_partial(
    TESTING_CONTRACT_PATH + "Minter.vy", compiler_args=compiler_args_default
)
FAKE_LEVERAGE_DEPLOYER = boa.load_partial(
    TESTING_CONTRACT_PATH + "FakeLeverage.vy", compiler_args=compiler_args_default
)
DUMMY_CALLBACK_DEPLOYER = boa.load_partial(
    TESTING_CONTRACT_PATH + "DummyCallback.vy", compiler_args=compiler_args_default
)
BLOCK_COUNTER_DEPLOYER = boa.load_partial(
    TESTING_CONTRACT_PATH + "BlockCounter.vy", compiler_args=compiler_args_default
)
DUMMY_FLASH_BORROWER_DEPLOYER = boa.load_partial(
    TESTING_CONTRACT_PATH + "DummyFlashBorrower.vy", compiler_args=compiler_args_default
)
DUMMY_LM_CALLBACK_DEPLOYER = boa.load_partial(
    TESTING_CONTRACT_PATH + "DummyLMCallback.vy", compiler_args=compiler_args_default
)
LM_CALLBACK_WITH_REVERTS_DEPLOYER = boa.load_partial(
    TESTING_CONTRACT_PATH + "LMCallbackWithReverts.vy",
    compiler_args=compiler_args_default,
)
MOCK_FACTORY_DEPLOYER = boa.load_partial(
    TESTING_CONTRACT_PATH + "MockFactory.vy", compiler_args=compiler_args_default
)
MOCK_MARKET_DEPLOYER = boa.load_partial(
    TESTING_CONTRACT_PATH + "MockMarket.vy", compiler_args=compiler_args_default
)
MOCK_RATE_SETTER_DEPLOYER = boa.load_partial(
    TESTING_CONTRACT_PATH + "MockRateSetter.vy", compiler_args=compiler_args_default
)
MOCK_PEG_KEEPER_DEPLOYER = boa.load_partial(
    TESTING_CONTRACT_PATH + "MockPegKeeper.vy", compiler_args=compiler_args_default
)
MOCK_RATE_ORACLE_DEPLOYER = boa.load_partial(
    TESTING_CONTRACT_PATH + "MockRateOracle.vy", compiler_args=compiler_args_default
)
CHAINLINK_AGGREGATOR_MOCK_DEPLOYER = boa.load_partial(
    TESTING_CONTRACT_PATH + "ChainlinkAggregatorMock.vy",
    compiler_args=compiler_args_default,
)
TRICRYPTO_MOCK_DEPLOYER = boa.load_partial(
    TESTING_CONTRACT_PATH + "TricryptoMock.vy", compiler_args=compiler_args_default
)
MOCK_SWAP2_DEPLOYER = boa.load_partial(
    TESTING_CONTRACT_PATH + "MockSwap2.vy", compiler_args=compiler_args_default
)
MOCK_SWAP3_DEPLOYER = boa.load_partial(
    TESTING_CONTRACT_PATH + "MockSwap3.vy", compiler_args=compiler_args_default
)
SWAP_FACTORY_DEPLOYER = boa.load_partial(
    TESTING_CONTRACT_PATH + "SwapFactory.vy", compiler_args=compiler_args_default
)

# LP oracle testing contracts
MOCK_STABLE_SWAP_DEPLOYER = boa.load_partial(
    PRICE_ORACLES_CONTRACT_PATH + "lp-oracles/testing/MockStableSwap.vy",
    compiler_args=compiler_args_default,
)
MOCK_CRYPTO_SWAP_DEPLOYER = boa.load_partial(
    PRICE_ORACLES_CONTRACT_PATH + "lp-oracles/testing/MockCryptoSwap.vy",
    compiler_args=compiler_args_default,
)
MOCK_STABLE_SWAP_NO_ARGUMENT_DEPLOYER = boa.load_partial(
    PRICE_ORACLES_CONTRACT_PATH + "lp-oracles/testing/MockStableSwapNoArgument.vy",
    compiler_args=compiler_args_default,
)

# Stableswap NG contracts
# TODO will fix
# CURVE_STABLESWAP_FACTORY_NG_DEPLOYER = boa.load_partial(
#     STABLESWAP_NG_PATH + "CurveStableSwapFactoryNG.vy",
#     compiler_args=compiler_args_default,
# )
# CurveStableSwapNG.vy has #pragma optimize codesize
# CURVE_STABLESWAP_NG_DEPLOYER = boa.load_partial(
#     STABLESWAP_NG_PATH + "CurveStableSwapNG.vy", compiler_args=compiler_args_codesize
# )
# # CurveStableSwapNGMath.vy has #pragma optimize gas
# CURVE_STABLESWAP_NG_MATH_DEPLOYER = boa.load_partial(
#     STABLESWAP_NG_PATH + "CurveStableSwapNGMath.vy", compiler_args=compiler_args_gas
# )
# CURVE_STABLESWAP_NG_VIEWS_DEPLOYER = boa.load_partial(
#     STABLESWAP_NG_PATH + "CurveStableSwapNGViews.vy",
#     compiler_args=compiler_args_default,
# )
