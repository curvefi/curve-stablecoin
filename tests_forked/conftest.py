from pathlib import Path

import pytest
from ape import Contract
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(Path(BASE_DIR, ".env"))


def pytest_configure():
    pytest.default_prices = (3000 * 10**18, 20000 * 10**18)


@pytest.fixture(scope="session")
def forked_admin(accounts):
    return accounts[0]


@pytest.fixture(scope="session")
def forked_fee_receiver(accounts):
    return accounts[1]


@pytest.fixture(scope="module")
def weth():
    return Contract("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")


@pytest.fixture(scope="session")
def collateral_token(project, forked_admin):
    return forked_admin.deploy(project.ERC20Mock, "Collateral", "ETH", 18)
