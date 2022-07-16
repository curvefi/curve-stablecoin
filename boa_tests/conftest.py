import boa
import pytest

# Patch EIP170 size limit because spurious dragon does the wrong code size
from eth.vm.forks.spurious_dragon import computation
computation.EIP170_CODE_SIZE_LIMIT = 640000  # 640 KB will be enough for everyone


PRICE = 3000


@pytest.fixture(scope="session")
def accounts():
    return [boa.env.generate_address() for i in range(10)]


@pytest.fixture(scope="session")
def admin():
    return boa.env.generate_address()


@pytest.fixture(scope="session")
def collateral_token(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/ERC20Mock.vy', "Colalteral", "ETH", 18)


@pytest.fixture(scope="session")
def price_oracle(admin):
    with boa.env.prank(admin):
        oracle = boa.load('contracts/testing/DummyPriceOracle.vy', admin, PRICE * 10**18)
        return oracle
