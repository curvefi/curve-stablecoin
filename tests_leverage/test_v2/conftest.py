import boa
import pytest

from .constants import (
    COLLATERALS,
    CRVUSD,
    FACTORIES,
    ONE_WAY_LENDING_FACTORY,
    ORACLE_POOLS,
    ROUTER,
)
from .settings import WEB3_PROVIDER_URL
from .utils import Router1inch, get_contract_from_explorer


def pytest_generate_tests(metafunc):
    if "collateral_info" in metafunc.fixturenames:
        collaterals = [
            {"address": v, "symbol": k, "oracle": ORACLE_POOLS[k]}
            for k, v in COLLATERALS.items()
        ]

        metafunc.parametrize(
            "collateral_info",
            collaterals,
            ids=[f"(Collateral={k['address']})" for k in collaterals],
        )


@pytest.fixture(autouse=True)
def forked_chain():
    assert (
        WEB3_PROVIDER_URL is not None
    ), "Provider url is not set, add WEB3_PROVIDER_URL param to env"
    boa.env.fork(url=WEB3_PROVIDER_URL)


@pytest.fixture()
def admin():
    return "0xbabe61887f1de2713c6f97e567623453d3C79f67"


@pytest.fixture(scope="session")
def amm_interface():
    return boa.load_partial("contracts/AMM.vy")


@pytest.fixture(scope="session")
def controller_interface():
    return boa.load_partial("contracts/Controller.vy")


@pytest.fixture(scope="session")
def vault_impl():
    return boa.load_partial("contracts/lending/Vault.vy")


@pytest.fixture()
def stablecoin():
    return boa.load_partial("contracts/Stablecoin.vy").at(CRVUSD)


@pytest.fixture()
def collateral(collateral_info):
    return get_contract_from_explorer(collateral_info["address"])


@pytest.fixture(scope="session")
def factory():
    return boa.load_partial("contracts/lending/OneWayLendingFactory.vy").at(
        ONE_WAY_LENDING_FACTORY
    )


@pytest.fixture()
def oracle_pool(collateral_info):
    return collateral_info["oracle"]


@pytest.fixture()
def vault(admin, factory, collateral, stablecoin, vault_impl, oracle_pool):
    boa.env.set_balance(admin, 200 * 10**18)  # 200 eth

    A = 70
    fee = int(0.002 * 1e18)
    borrowing_discount = int(0.07 * 1e18)
    liquidation_discount = int(0.04 * 1e18)
    min_borrow_rate = 5 * 10**15 // (365 * 86400)  # 0.5%
    max_borrow_rate = 80 * 10**16 // (365 * 86400)  # 80%

    with boa.env.prank(admin):
        vault = vault_impl.at(
            factory.create_from_pool(
                stablecoin,
                collateral,
                A,
                fee,
                borrowing_discount,
                liquidation_discount,
                oracle_pool,
                "test",
                min_borrow_rate,
                max_borrow_rate,
            )
        )

        swap = get_contract_from_explorer("0x4eBdF703948ddCEA3B11f675B4D1Fba9d2414A14")

        weth = get_contract_from_explorer("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")
        weth.deposit(value=20 * 10**18)
        weth.approve(swap.address, 20 * 10**18)
        swap.exchange(1, 0, 20 * 10**18, 0)

        stablecoin.approve(vault.address, 50 * 1000 * 10**18)
        vault.deposit(50 * 1000 * 10**18)

    return vault


@pytest.fixture()
def controller(vault, controller_interface):
    return controller_interface.at(vault.controller())


@pytest.fixture()
def user_collateral_amount(collateral):
    return 1 * 10 ** collateral.decimals()


@pytest.fixture()
def alice(collateral_info, user_collateral_amount, controller):
    user = boa.env.generate_address()
    boa.env.set_balance(user, 200 * 10**18)  # 200 eth

    with boa.env.prank(user):
        if collateral_info["symbol"] == "WETH":
            weth = get_contract_from_explorer(
                "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
            )
            weth.deposit(value=user_collateral_amount)
            weth.approve(controller.AMM(), user_collateral_amount)

    return user


@pytest.fixture()
def leverage_zap_1inch():
    return boa.load("contracts/zaps/LeverageZap1inch.vy", ROUTER, FACTORIES)


@pytest.fixture(scope="session")
def router_api_1inch():
    return Router1inch(1)
