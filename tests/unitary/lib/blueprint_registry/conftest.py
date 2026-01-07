import boa
import pytest


@pytest.fixture()
def blueprint_registry_deployer():
    return boa.loads_partial("""
from curve_stablecoin.lending import blueprint_registry

initializes: blueprint_registry

@deploy
def __init__(_allowed_ids: DynArray[String[4], 10]):
    blueprint_registry.__init__(_allowed_ids)

@external
def set(_id: String[4], _address: address):
    blueprint_registry.set(_id, _address)

@external
@view
def get(_id: String[4]) -> address:
    return blueprint_registry.get(_id)

@external
@view
def in_array(_value: String[4], _array: DynArray[String[4], 10]) -> bool:
    return blueprint_registry.in_array(_value, _array)

@external
@view
def get_all_ids() -> DynArray[String[4], 10]:
    return blueprint_registry.BLUEPRINT_REGISTRY_IDS
""")


@pytest.fixture()
def blueprint_registry(blueprint_registry_deployer):
    return blueprint_registry_deployer(["AMM", "CTR", "VLT", "CTRV"])
