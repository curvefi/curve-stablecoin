import boa
import pytest


@pytest.fixture(scope="module", autouse=True)
def accounts():
    return [i.to_bytes(length=20, byteorder='little') for i in range(10)]


@pytest.fixture(scope="module", autouse=True)
def admin():
    return (1337).to_bytes(length=20, byteorder='big')


@pytest.fixture(scope="module", autouse=True)
def stablecoin(accounts, admin):
    with boa.env.prank(admin):
        return boa.load('contracts/Stablecoin.vy', 'Curve USD', 'crvUSD')


def test_stablecoin(stablecoin):
    assert stablecoin.decimals() == 18
