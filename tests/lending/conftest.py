import boa
import pytest
from itertools import product


@pytest.fixture(scope="session")
def amm_interface():
    return boa.load_partial('contracts/AMM.vy')


@pytest.fixture(scope="session")
def amm_impl(amm_interface, admin):
    with boa.env.prank(admin):
        return amm_interface.deploy_as_blueprint()


@pytest.fixture(scope="session")
def controller_interface():
    return boa.load_partial('contracts/Controller.vy')


@pytest.fixture(scope="session")
def controller_impl(controller_interface, admin):
    with boa.env.prank(admin):
        return controller_interface.deploy_as_blueprint()


@pytest.fixture(scope="module")
def stablecoin(get_borrowed_token):
    return get_borrowed_token(18)


@pytest.fixture(scope="session")
def vault_impl(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/lending/Vault.vy')


@pytest.fixture(scope="session")
def price_oracle_interface():
    return boa.load_partial('contracts/price_oracles/CryptoFromPool.vy')


@pytest.fixture(scope="session")
def price_oracle_impl(price_oracle_interface, admin):
    with boa.env.prank(admin):
        return price_oracle_interface.deploy_as_blueprint()


@pytest.fixture(scope="session")
def mpolicy_interface():
    return boa.load_partial('contracts/mpolicies/SemilogMonetaryPolicy.vy')


@pytest.fixture(scope="session")
def mpolicy_impl(mpolicy_interface, admin):
    with boa.env.prank(admin):
        return mpolicy_interface.deploy_as_blueprint()


@pytest.fixture(scope="session")
def gauge_impl(admin):
    with boa.env.prank(admin):
        return boa.load_partial('contracts/testing/MockGauge.vy').deploy_as_blueprint()


@pytest.fixture(scope="session")
def factory_partial():
    return boa.load_partial('contracts/lending/OneWayLendingFactory.vy')


@pytest.fixture(scope="module")
def factory(factory_partial, stablecoin, amm_impl, controller_impl, vault_impl, price_oracle_impl, mpolicy_impl, gauge_impl, admin):
    with boa.env.prank(admin):
        return factory_partial.deploy(
            stablecoin.address,
            amm_impl, controller_impl, vault_impl,
            price_oracle_impl, mpolicy_impl, gauge_impl,
            admin)


@pytest.fixture(scope="module", params=product([2, 6, 8, 18], [True, False]))
def tokens_for_vault(get_collateral_token, stablecoin, request):
    decimals, stablecoin_is_borrowed = request.param
    token = get_collateral_token(decimals)
    if stablecoin_is_borrowed:
        borrowed_token = stablecoin
        collateral_token = token
    else:
        borrowed_token = token
        collateral_token = stablecoin
    return borrowed_token, collateral_token


@pytest.fixture(scope="module")
def collateral_token(tokens_for_vault):
    return tokens_for_vault[1]


@pytest.fixture(scope="module")
def borrowed_token(tokens_for_vault):
    return tokens_for_vault[0]


@pytest.fixture(scope="module")
def vault(factory, vault_impl, collateral_token, borrowed_token, price_oracle, admin):
    with boa.env.prank(admin):
        return vault_impl.at(
            factory.create(
                borrowed_token.address, collateral_token.address,
                100, int(0.006 * 1e18), int(0.09 * 1e18), int(0.06 * 1e18),
                price_oracle.address, "Test vault"
            )
        )


@pytest.fixture(scope="module")
def market_controller(vault, controller_interface):
    return controller_interface.at(vault.controller())


@pytest.fixture(scope="module")
def market_amm(vault, amm_interface):
    return amm_interface.at(vault.amm())


@pytest.fixture(scope="module")
def market_mpolicy(market_controller, mpolicy_interface):
    return mpolicy_interface.at(market_controller.monetary_policy())


@pytest.fixture(scope="session")
def mock_token_interface():
    return boa.load_partial('contracts/testing/ERC20Mock.vy')


@pytest.fixture(scope="module")
def filled_controller(vault, borrowed_token, market_controller, admin):
    with boa.env.prank(admin):
        amount = 100 * 10**6 * 10**(borrowed_token.decimals())
        borrowed_token._mint_for_testing(admin, amount)
        borrowed_token.approve(vault.address, 2**256 - 1)
        vault.deposit(amount)
    return market_controller


@pytest.fixture(scope="module")
def fake_leverage(collateral_token, borrowed_token, market_controller, admin):
    with boa.env.prank(admin):
        leverage = boa.load('contracts/testing/FakeLeverage.vy', borrowed_token.address, collateral_token.address,
                            market_controller.address, 3000 * 10**18)
        collateral_token._mint_for_testing(leverage.address, 1000 * 10**collateral_token.decimals())
        return leverage
