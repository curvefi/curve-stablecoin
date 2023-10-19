import os
import pytest
from pathlib import Path
from hypothesis import settings
from ape import project, accounts, Contract
from dotenv import load_dotenv
from .utils import mint_tokens_for_testing, mint_crvusd_tokens_for_testing, ROUTER_PARAMS, ROUTER_PARAMS_DELEVERAGE, COLLATERALS, CONTROLLERS, LLAMMAS, ROUTERS

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(Path(BASE_DIR, ".env"))

settings.register_profile("default", max_examples=10, deadline=None)
settings.load_profile(os.getenv(u"HYPOTHESIS_PROFILE", "default"))


"""
We use autouse=True to automatically deploy all during all tests
"""


@pytest.fixture(scope="module", autouse=True)
def admin(accounts):
    acc = accounts[0]
    mint_crvusd_tokens_for_testing(project, acc)
    return acc


@pytest.fixture(scope="module", autouse=True)
def user(project, accounts):
    acc = accounts[1]
    mint_tokens_for_testing(project, acc)
    return acc


@pytest.fixture(scope="module", autouse=True)
def stablecoin_token():
    return Contract("0xf939e0a03fb07f59a73314e73794be0e57ac1b4e")


@pytest.fixture(scope="module", autouse=True)
def controllers():
    controller_contracts = {}
    for collateral in COLLATERALS.keys():
        controller_contracts[collateral] = Contract(CONTROLLERS[collateral])
    return controller_contracts


@pytest.fixture(scope="module", autouse=True)
def llammas(stablecoin_token, admin):
    amm_contracts = {}
    for collateral in COLLATERALS.keys():
        amm_contracts[collateral] = Contract(LLAMMAS[collateral])
        stablecoin_token.approve(amm_contracts[collateral], 2**256 - 1, sender=admin)
    return amm_contracts


@pytest.fixture(scope="module", autouse=True)
def collaterals(user):
    collateral_contracts = {}
    for collateral in COLLATERALS.keys():
        collateral_contracts[collateral] = Contract(COLLATERALS[collateral])
        # No need to give approval for WETH because we will use ETH, but it doesn't matter
        collateral_contracts[collateral].approve(CONTROLLERS[collateral], 2**256 - 1, sender=user)
    return collateral_contracts


@pytest.fixture(scope="module", autouse=True)
def leverage_zaps(project, admin):
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

        contract = project.LeverageZap
        if collateral == "sfrxETH":
            contract = project.LeverageZapSfrxETH
        if collateral == "wstETH":
            contract = project.LeverageZapWstETH
        if collateral in ["sfrxETH2", "tBTC"]:
            contract = project.LeverageZapNewRouter
        leverage_contracts[collateral] = contract.deploy(
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


@pytest.fixture(scope="module", autouse=True)
def deleverage_zaps(project, admin):
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

        deleverage_contracts[collateral] = project.DeleverageZap.deploy(
            CONTROLLERS[collateral],
            COLLATERALS[collateral],
            "0xF0d4c12A5768D806021F80a262B4d39d26C58b8D",
            routes,
            route_params,
            route_pools,
            route_names,
            sender=admin,
        )
    return deleverage_contracts
