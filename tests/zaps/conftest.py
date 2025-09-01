import boa
import pytest

from tests.utils.deploy import Protocol

from tests.utils.deployers import (
    # Core contracts
    STABLECOIN_DEPLOYER,
    AMM_DEPLOYER,
    MINT_CONTROLLER_DEPLOYER,
    CONTROLLER_FACTORY_DEPLOYER,
    # Lending contracts
    VAULT_DEPLOYER,
    LL_CONTROLLER_DEPLOYER,
    LL_CONTROLLER_VIEW_DEPLOYER,
    LENDING_FACTORY_DEPLOYER,
    # Price oracles
    DUMMY_PRICE_ORACLE_DEPLOYER,
    CRYPTO_FROM_POOL_DEPLOYER,
    # Monetary policies
    CONSTANT_MONETARY_POLICY_DEPLOYER,
    CONSTANT_MONETARY_POLICY_LENDING_DEPLOYER,
    # Testing contracts
    WETH_DEPLOYER,
    ERC20_MOCK_DEPLOYER,
)


@pytest.fixture(scope="module")
def tokens_for_vault(admin, stablecoin):
    with boa.env.prank(admin):
        token = ERC20_MOCK_DEPLOYER.deploy(18)
    return stablecoin, token


@pytest.fixture(scope="module")
def collateral_token(tokens_for_vault):
    return tokens_for_vault[1]


@pytest.fixture(scope="module")
def borrowed_token(tokens_for_vault):
    return tokens_for_vault[0]


@pytest.fixture(scope="module")
def lending_market(proto, borrowed_token, collateral_token, price_oracle, admin):
    """Create a lending market using a constant-rate lending policy via Protocol hook."""
    with boa.env.prank(admin):
        return proto.create_lending_market(
            borrowed_token=borrowed_token,
            collateral_token=collateral_token,
            A=100,
            fee=int(0.006 * 1e18),
            loan_discount=int(0.09 * 1e18),
            liquidation_discount=int(0.06 * 1e18),
            price_oracle=price_oracle,
            name="Test vault",
            min_borrow_rate=int(0.005 * 1e18) // (365 * 86400),  # 0.5% APR
            max_borrow_rate=int(0.5 * 1e18) // (365 * 86400),  # 50% APR
            mpolicy_deployer=CONSTANT_MONETARY_POLICY_LENDING_DEPLOYER,
        )


@pytest.fixture(scope="module")
def vault(lending_market):
    return lending_market["vault"]


@pytest.fixture(scope="module")
def market_controller(lending_market, admin):
    controller = lending_market["controller"]
    with boa.env.prank(admin):
        controller.set_borrow_cap(2**256 - 1)
    return controller


@pytest.fixture(scope="module")
def market_amm(lending_market):
    return lending_market["amm"]


@pytest.fixture(scope="module")
def market_mpolicy(market_controller):
    return CONSTANT_MONETARY_POLICY_LENDING_DEPLOYER.at(market_controller.monetary_policy())


@pytest.fixture(scope="module")
def filled_controller(vault, borrowed_token, market_controller, admin):
    with boa.env.prank(admin):
        amount = 100 * 10**6 * 10 ** (borrowed_token.decimals())
        boa.deal(borrowed_token, admin, amount)
        borrowed_token.approve(vault.address, 2**256 - 1)
        vault.deposit(amount)
    return market_controller
