from pytest import fixture
from tests.utils.deploy import Protocol
from tests.utils.deployers import ERC20_MOCK_DEPLOYER

@fixture(scope="module")
def proto():
    return Protocol()

@fixture(scope="module")
def admin(proto: Protocol):
    return proto.admin

@fixture(scope="module", params=range(2, 19))
def decimals(request):
    return request.param

@fixture(scope="module")
def collat(decimals):
    return ERC20_MOCK_DEPLOYER.deploy(decimals)
