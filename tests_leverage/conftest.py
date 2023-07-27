import os
import pytest
from pathlib import Path
from datetime import timedelta
from hypothesis import settings
from ape import project, accounts, Contract
from dotenv import load_dotenv
from .utils import mint_tokens_for_testing, ROUTER_PARAMS, COLLATERALS, CONTROLLERS, LLAMMAS, ROUTER

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
    return acc


@pytest.fixture(scope="module", autouse=True)
def user(project, accounts):
    acc = accounts[1]
    mint_tokens_for_testing(project, acc)
    return acc


@pytest.fixture(scope="module", autouse=True)
def controllers():
    controller_contracts = {}
    for collateral in COLLATERALS.keys():
        controller_contracts[collateral] = Contract(CONTROLLERS[collateral])
    return controller_contracts


@pytest.fixture(scope="module", autouse=True)
def llammas():
    amm_contracts = {}
    for collateral in COLLATERALS.keys():
        amm_contracts[collateral] = Contract(LLAMMAS[collateral])
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
        leverage_contracts[collateral] = contract.deploy(
            CONTROLLERS[collateral],
            COLLATERALS[collateral],
            ROUTER,
            routes,
            route_params,
            route_pools,
            route_names,
            sender=admin,
        )
    return leverage_contracts
