import boa
import pytest
from tests.forked.settings import WEB3_PROVIDER_URL, EXPLORER_TOKEN
from tests.utils.deployers import (
    ERC20_MOCK_DEPLOYER,
    CONTROLLER_VIEW_DEPLOYER,
    AMM_DEPLOYER,
    DUMMY_PRICE_ORACLE_DEPLOYER,
    CONSTANT_MONETARY_POLICY_DEPLOYER,
)


@pytest.fixture(scope="module", autouse=True)
def boa_fork():
    assert WEB3_PROVIDER_URL is not None, (
        "Provider url is not set, add WEB3_PROVIDER_URL param to env"
    )
    boa.fork(WEB3_PROVIDER_URL, allow_dirty=True)


@pytest.fixture(scope="module", autouse=True)
def api_key():
    with boa.set_etherscan(api_key=EXPLORER_TOKEN):
        yield


@pytest.fixture(scope="module")
def mint_factory():
    return boa.from_etherscan(
        "0xC9332fdCB1C491Dcc683bAe86Fe3cb70360738BC",
        name="MintFactory",
    )


@pytest.fixture(scope="module")
def admin(mint_factory):
    return mint_factory.admin()


@pytest.fixture(scope="module")
def controller_blueprint():
    controller_view_blueprint = CONTROLLER_VIEW_DEPLOYER.deploy_as_blueprint()

    with open("curve_stablecoin/MintController.vy", "r") as f:
        mint_controller_code = f.read()
    mint_controller_code = mint_controller_code.replace(
        "empty(address),  # to replace at deployment with view blueprint",
        f"{controller_view_blueprint.address},",
        1,
    )
    assert f"{controller_view_blueprint.address}," in mint_controller_code

    return boa.loads_partial(mint_controller_code).deploy_as_blueprint()


@pytest.fixture(scope="module")
def amm_blueprint():
    return AMM_DEPLOYER.deploy_as_blueprint()


@pytest.fixture(scope="module")
def collateral_token():
    return ERC20_MOCK_DEPLOYER.deploy(18)


@pytest.fixture(scope="module")
def crvusd(mint_factory):
    return ERC20_MOCK_DEPLOYER.at(mint_factory.stablecoin())


@pytest.fixture(scope="module")
def price_oracle(admin):
    return DUMMY_PRICE_ORACLE_DEPLOYER.deploy(admin, 100 * 10**18, sender=admin)


@pytest.fixture(scope="module")
def monetary_policy(admin):
    return CONSTANT_MONETARY_POLICY_DEPLOYER.deploy(admin, sender=admin)
