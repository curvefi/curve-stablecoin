import boa
import pytest
from .settings import WEB3_PROVIDER_URL
from .utils import ROUTER_PARAMS, ROUTER_PARAMS_DELEVERAGE, COLLATERALS, CONTROLLERS, LLAMMAS, ROUTERS, ROUTERS_DELEVERAGE

"""
We use autouse=True to automatically deploy all during all tests
"""


@pytest.fixture(scope="session", autouse=True)
def boa_fork():
    assert WEB3_PROVIDER_URL is not None, "Provider url is not set, add WEB3_PROVIDER_URL param to env"
    boa.fork(WEB3_PROVIDER_URL)


@pytest.fixture(scope="module")
def admin():
    return boa.env.generate_address()


@pytest.fixture(scope="module")
def user():
    return boa.env.generate_address()


@pytest.fixture(scope="module")
def stablecoin_token():
    return boa.load_partial("contracts/Stablecoin.vy").at("0xf939e0a03fb07f59a73314e73794be0e57ac1b4e")


@pytest.fixture(scope="module")
def controllers():
    controller_contracts = {}
    for collateral in COLLATERALS.keys():
        controller_contracts[collateral] = boa.load_partial("contracts/Controller.vy").at(CONTROLLERS[collateral])
    return controller_contracts


@pytest.fixture(scope="module")
def llammas(stablecoin_token, admin):
    amm_contracts = {}
    for collateral in COLLATERALS.keys():
        amm_contracts[collateral] = boa.load_partial("contracts/AMM.vy").at(LLAMMAS[collateral])
        stablecoin_token.approve(amm_contracts[collateral], 2**256 - 1, sender=admin)
    return amm_contracts


@pytest.fixture(scope="module")
def collaterals(user):
    collateral_contracts = {}
    for collateral in COLLATERALS.keys():
        collateral_contracts[collateral] = boa.load_partial("contracts/testing/ERC20Mock.vy").at(COLLATERALS[collateral])
        # No need to give approval for WETH because we will use ETH, but it doesn't matter
        collateral_contracts[collateral].approve(CONTROLLERS[collateral], 2**256 - 1, sender=user)
    return collateral_contracts


@pytest.fixture(scope="module")
def leverage_zaps(admin):
    leverage_contracts = {}
    for collateral in COLLATERALS.keys():
        routes = []
        route_params = []
        route_pools = []
        route_names = []
        for route in ROUTER_PARAMS[collateral].values():
            routes.append(route["route"])
            route_params.append(route["swap_params"])
            route_pools.append(route["factory_swap_addresses"])
            route_names.append(route["name"])

        interface = boa.load_partial("contracts/zaps/deprecated/LeverageZap.vy")
        if collateral == "sfrxETH":
            interface = boa.load_partial("contracts/zaps/deprecated/LeverageZapSfrxETH.vy")
        if collateral == "wstETH":
            interface = boa.load_partial("contracts/zaps/deprecated/LeverageZapWstETH.vy")
        if collateral in ["sfrxETH2", "WBTC", "tBTC"]:
            interface = boa.load_partial("contracts/zaps/deprecated/LeverageZapNewRouter.vy")
        leverage_contracts[collateral] = interface.deploy(
            CONTROLLERS[collateral],
            COLLATERALS[collateral],
            ROUTERS[collateral],
            routes,
            route_params,
            route_pools,
            route_names,
            sender=admin,
        )
    return leverage_contracts


@pytest.fixture(scope="module")
def deleverage_zaps(admin):
    deleverage_contracts = {}
    for collateral in COLLATERALS.keys():
        routes = []
        route_params = []
        route_pools = []
        route_names = []
        for route in ROUTER_PARAMS_DELEVERAGE[collateral].values():
            routes.append(route["route"])
            route_params.append(route["swap_params"])
            route_pools.append(route["factory_swap_addresses"])
            route_names.append(route["name"])

        deleverage_contracts[collateral] = boa.load("contracts/zaps/deprecated/DeleverageZap.vy",
            CONTROLLERS[collateral],
            COLLATERALS[collateral],
            ROUTERS_DELEVERAGE[collateral],
            routes,
            route_params,
            route_pools,
            route_names,
            sender=admin,
        )
    return deleverage_contracts


@pytest.fixture(scope="module", autouse=True)
def mint_tokens_for_testing(user):
    """
    Provides given account with 100 WBTC and 1000 ETH, sfrxETH, wstETH
    Can be used only on local forked mainnet

    :return: None
    """

    # WBTC
    token = boa.load_partial("contracts/testing/ERC20Mock.vy").at("0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599")
    amount = 100 * 10**8
    boa.deal(token, user, amount)

    # tBTC
    token = boa.load_partial("contracts/testing/ERC20Mock.vy").at("0x18084fbA666a33d37592fA2633fD49a74DD93a88")
    amount = 100 * 10 ** 18
    boa.deal(token, user, amount)

    # ETH
    # Set balance to twice amount + 1 - half will be wrapped + (potential) gas
    boa.env.set_balance(user, 1000 * 10**18)

    # sfrxETH
    token = boa.load_partial("contracts/testing/ERC20Mock.vy").at("0xac3e018457b222d93114458476f3e3416abbe38f")
    amount = 1000 * 10**18
    boa.deal(token, user, amount)

    # wstETH
    token = boa.load_partial("contracts/testing/ERC20Mock.vy").at("0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0")
    amount = 1000 * 10 ** 18
    boa.deal(token, user, amount)

    # crvUSD
    token = boa.load_partial("contracts/testing/ERC20Mock.vy").at("0xf939e0a03fb07f59a73314e73794be0e57ac1b4e")
    amount = 100_000_000 * 10 ** 18
    boa.deal(token, user, amount)
