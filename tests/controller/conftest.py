from pytest import fixture
from tests.utils.deployers import ERC20_MOCK_DEPLOYER

# Common fixtures (proto, admin) are now in tests/conftest.py


@fixture(scope="module", params=[2, 6, 8, 9, 18])
def decimals(request):
    return request.param


@fixture(scope="module")
def collat(decimals):
    return ERC20_MOCK_DEPLOYER.deploy(decimals)


@fixture(scope="module")
def borrow(decimals):
    return ERC20_MOCK_DEPLOYER.deploy(decimals)
