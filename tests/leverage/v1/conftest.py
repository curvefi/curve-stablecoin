import os
import boa
import pytest
from v1.constants import (
    ROUTER_PARAMS,
    ROUTER_PARAMS_DELEVERAGE,
    COLLATERALS,
    CONTROLLERS,
    LLAMMAS,
    ROUTERS,
    ROUTERS_DELEVERAGE,
    CRVUSD,
)


@pytest.fixture(scope="module", autouse=True)
def boa_fork():
    WEB3_PROVIDER_URL = os.getenv("WEB3_PROVIDER_URL")
    assert WEB3_PROVIDER_URL is not None, (
        "Provider url is not set, add WEB3_PROVIDER_URL param to env"
    )
    boa.fork(WEB3_PROVIDER_URL)


@pytest.fixture(scope="module")
def trader():
    return boa.env.generate_address()


@pytest.fixture(scope="module")
def user():
    return boa.env.generate_address()


@pytest.fixture(scope="module")
def stablecoin_token():
    return boa.load_partial("contracts/Stablecoin.vy").at(CRVUSD)


@pytest.fixture(scope="module")
def controllers():
    controller_contracts = {}
    for collateral in COLLATERALS.keys():
        controller_contracts[collateral] = boa.load_partial(
            "contracts/Controller.vy"
        ).at(CONTROLLERS[collateral])
    return controller_contracts


@pytest.fixture(scope="module")
def llammas(stablecoin_token, trader):
    amm_contracts = {}
    for collateral in COLLATERALS.keys():
        amm_contracts[collateral] = boa.load_partial("contracts/AMM.vy").at(
            LLAMMAS[collateral]
        )
        stablecoin_token.approve(amm_contracts[collateral], 2**256 - 1, sender=trader)
    return amm_contracts


@pytest.fixture(scope="module")
def collaterals(user):
    collateral_contracts = {}
    for collateral in COLLATERALS.keys():
        collateral_contracts[collateral] = boa.load_partial(
            "contracts/testing/ERC20Mock.vy"
        ).at(COLLATERALS[collateral])
        # No need to give approval for WETH because we will use ETH, but it doesn't matter
        collateral_contracts[collateral].approve(
            CONTROLLERS[collateral], 2**256 - 1, sender=user
        )
    return collateral_contracts


@pytest.fixture(scope="module", autouse=True)
def mint_tokens_for_testing(user, trader, collaterals, stablecoin_token):
    # User
    for k in collaterals.keys():
        if k == "WETH":
            continue
        boa.deal(collaterals[k], user, 1000 * 10 ** collaterals[k].decimals())
    boa.env.set_balance(user, 1000 * 10**18)

    # Trader
    boa.deal(stablecoin_token, trader, 100_000_000 * 10**18)


@pytest.fixture(scope="module")
def leverage_zaps():
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
            interface = boa.load_partial(
                "contracts/zaps/deprecated/LeverageZapSfrxETH.vy"
            )
        if collateral == "wstETH":
            interface = boa.load_partial(
                "contracts/zaps/deprecated/LeverageZapWstETH.vy"
            )
        if collateral in ["sfrxETH2", "WBTC", "tBTC"]:
            interface = boa.load_partial(
                "contracts/zaps/deprecated/LeverageZapNewRouter.vy"
            )
        leverage_contracts[collateral] = interface.deploy(
            CONTROLLERS[collateral],
            COLLATERALS[collateral],
            ROUTERS[collateral],
            routes,
            route_params,
            route_pools,
            route_names,
        )

    return leverage_contracts


@pytest.fixture(scope="module")
def deleverage_zaps():
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

        deleverage_contracts[collateral] = boa.load(
            "contracts/zaps/deprecated/DeleverageZap.vy",
            CONTROLLERS[collateral],
            COLLATERALS[collateral],
            ROUTERS_DELEVERAGE[collateral],
            routes,
            route_params,
            route_pools,
            route_names,
        )

    return deleverage_contracts
