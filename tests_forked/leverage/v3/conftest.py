import os
import boa
import pytest


# ARBITRUM ONLY
@pytest.fixture(scope="module", autouse=True)
def forked_chain():
    WEB3_PROVIDER_URL = os.getenv("WEB3_PROVIDER_URL")
    assert WEB3_PROVIDER_URL is not None, "Provider url is not set, add WEB3_PROVIDER_URL param to env"
    boa.fork(url=WEB3_PROVIDER_URL)


@pytest.fixture(scope="module")
def controller():
    return boa.load_partial("contracts/Controller.vy").at("0xB5c6082d3307088C98dA8D79991501E113e6365d")


@pytest.fixture(scope="module")
def weth():
    return boa.load_partial("contracts/testing/WETH.vy").at("0x82aF49447D8a07e3bd95BD0d56f35241523fBab1")


@pytest.fixture(scope="module")
def crvusd():
    return boa.load_partial("contracts/Stablecoin.vy").at("0x498Bf2B1e120FeD3ad3D42EA2165E9b73f99C1e5")


@pytest.fixture(scope="module")
def borrower(weth):
    user = boa.env.generate_address()
    boa.env.set_balance(user, 200 * 10**18)  # 200 eth
    weth.deposit(value=200 * 10**18, sender=user)

    return user


@pytest.fixture(scope="module")
def leverage_zap():
    return boa.load("contracts/zaps/LeverageZap.vy", ["0xcaEC110C784c9DF37240a8Ce096D352A75922DeA"])


@pytest.fixture(scope="module")
def router(weth, crvusd):
    r = boa.load("contracts/testing/DummyRouter.vy")
    boa.deal(weth, r.address, 10**20)
    boa.deal(crvusd, r.address, 10**24)

    return r
