import pytest


@pytest.fixture(scope="module")
def market_type():
    return "lending"
