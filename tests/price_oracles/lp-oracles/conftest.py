import boa
import pytest
import random
from tests.utils.deployers import (
    WETH_DEPLOYER,
    DUMMY_PRICE_ORACLE_DEPLOYER,
    MOCK_STABLE_SWAP_DEPLOYER,
    MOCK_CRYPTO_SWAP_DEPLOYER,
    MOCK_STABLE_SWAP_NO_ARGUMENT_DEPLOYER,
    PROXY_ORACLE_DEPLOYER,
    PROXY_ORACLE_FACTORY_DEPLOYER,
    LP_ORACLE_STABLE_DEPLOYER,
    LP_ORACLE_CRYPTO_DEPLOYER,
    LP_ORACLE_FACTORY_DEPLOYER,
)


@pytest.fixture(scope="module")
def broken_contract(admin):
    with boa.env.prank(admin):
        return WETH_DEPLOYER.deploy()


@pytest.fixture(scope="module")
def coin0_oracle(admin):
    with boa.env.prank(admin):
        return DUMMY_PRICE_ORACLE_DEPLOYER.deploy(
            admin, random.randint(99 * 10**17, 101 * 10**17)
        )


@pytest.fixture(scope="module")
def get_stable_swap(admin):
    def f(N):
        prices = [random.randint(10**16, 10**23) for i in range(N - 1)]
        with boa.env.prank(admin):
            return MOCK_STABLE_SWAP_DEPLOYER.deploy(admin, prices)

    return f


@pytest.fixture(scope="module")
def crypto_swap(admin):
    with boa.env.prank(admin):
        return MOCK_CRYPTO_SWAP_DEPLOYER.deploy(admin, random.randint(10**16, 10**23))


@pytest.fixture(scope="module")
def stable_swap_no_argument(admin):
    with boa.env.prank(admin):
        return MOCK_STABLE_SWAP_NO_ARGUMENT_DEPLOYER.deploy(
            admin, random.randint(10**16, 10**23)
        )


@pytest.fixture(scope="module")
def proxy_impl(admin):
    with boa.env.prank(admin):
        return PROXY_ORACLE_DEPLOYER.deploy()


@pytest.fixture(scope="module")
def proxy_factory(admin, proxy_impl):
    with boa.env.prank(admin):
        return PROXY_ORACLE_FACTORY_DEPLOYER.deploy(admin, proxy_impl)


@pytest.fixture(scope="module")
def lp_oracle_stable_impl(admin):
    with boa.env.prank(admin):
        return LP_ORACLE_STABLE_DEPLOYER.deploy_as_blueprint()


@pytest.fixture(scope="module")
def lp_oracle_crypto_impl(admin):
    with boa.env.prank(admin):
        return LP_ORACLE_CRYPTO_DEPLOYER.deploy_as_blueprint()


@pytest.fixture(scope="module")
def lp_oracle_factory(
    admin, lp_oracle_stable_impl, lp_oracle_crypto_impl, proxy_factory
):
    with boa.env.prank(admin):
        return LP_ORACLE_FACTORY_DEPLOYER.deploy(
            admin, lp_oracle_stable_impl, lp_oracle_crypto_impl, proxy_factory
        )


@pytest.fixture(scope="module")
def get_lp_oracle_stable(admin):
    def f(pool, coin0_oracle):
        with boa.env.prank(admin):
            return LP_ORACLE_STABLE_DEPLOYER.deploy(pool, coin0_oracle)

    return f


@pytest.fixture(scope="module")
def get_lp_oracle_crypto(admin):
    def f(pool, coin0_oracle):
        with boa.env.prank(admin):
            return LP_ORACLE_CRYPTO_DEPLOYER.deploy(pool, coin0_oracle)

    return f
