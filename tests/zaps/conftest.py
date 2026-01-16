import pytest


@pytest.fixture(scope="module")
def amm_A():
    return 100


@pytest.fixture(scope="module")
def seed_liquidity(borrowed_token):
    # Match the seeding used by these tests (assumes 18 decimals)
    return 100 * 10**6 * 10 ** borrowed_token.decimals()
