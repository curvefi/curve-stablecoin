import boa
import pytest

from .constants import COLLATERALS, CONTROLLERS, CRVUSD, FACTORIES, ROUTER
from .constants import frxETH as frxETH_address
from .settings import WEB3_PROVIDER_URL
from .utils import Router1inch, get_contract_from_explorer


def pytest_generate_tests(metafunc):
    if "collateral_info" in metafunc.fixturenames:
        collaterals = [
            {"address": v, "controller": CONTROLLERS[k], "symbol": k}
            for k, v in COLLATERALS.items()
        ]

        metafunc.parametrize(
            "collateral_info",
            collaterals,
            ids=[f"(ControllerInfo={k['address']})" for k in collaterals],
        )


@pytest.fixture(autouse=True)
def forked_chain():
    assert WEB3_PROVIDER_URL is not None, (
        "Provider url is not set, add WEB3_PROVIDER_URL param to env"
    )
    boa.env.fork(url=WEB3_PROVIDER_URL)


@pytest.fixture()
def alice(collateral_info):
    user = boa.env.generate_address()
    boa.env.set_balance(user, 200 * 10**18)  # 200 eth

    with boa.env.prank(user):
        if collateral_info["symbol"] == "sfrxETH":
            swap = get_contract_from_explorer(
                "0xa1F8A6807c402E4A15ef4EBa36528A3FED24E577"
            )
            swap.exchange(0, 1, 2 * 10**18, 1 * 10**18, value=2 * 10**18)
            sfrxETH = get_contract_from_explorer(collateral_info["address"])
            frxETH = get_contract_from_explorer(frxETH_address)
            frxETH.approve(sfrxETH.address, 10**18)
            sfrxETH.deposit(10**18, user)

    return user


@pytest.fixture(scope="session")
def controller_interface():
    return boa.load_partial("contracts/Controller.vy")


@pytest.fixture()
def stablecoin():
    return boa.load_partial("contracts/Stablecoin.vy").at(CRVUSD)


@pytest.fixture()
def collateral(collateral_info):
    return get_contract_from_explorer(collateral_info["address"])


@pytest.fixture()
def controller(collateral_info, controller_interface):
    return controller_interface.at(collateral_info["controller"])


@pytest.fixture()
def leverage_zap_1inch():
    return boa.load("contracts/zaps/LeverageZap1inch.vy", ROUTER, FACTORIES)


@pytest.fixture(scope="session")
def router_api_1inch():
    return Router1inch(1)
