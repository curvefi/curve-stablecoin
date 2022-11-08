import pytest


@pytest.fixture(scope="session")
def alice(accounts):
    yield accounts[0]


@pytest.fixture(scope="session")
def bob(accounts):
    yield accounts[1]


@pytest.fixture(scope="session")
def charlie(accounts):
    yield accounts[2]


@pytest.fixture(scope="module")
def stablecoin(alice, Stablecoin):
    yield Stablecoin.deploy("CurveFi USD Stablecoin", "crvUSD", {"from": alice})


@pytest.fixture(autouse=True)
def isolate(fn_isolation):
    ...