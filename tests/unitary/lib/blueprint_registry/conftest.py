import boa
import pytest


@pytest.fixture()
def blueprint_registry_deployer():
    return boa.load_partial("curve_stablecoin/lib/blueprint_registry.vy")


@pytest.fixture()
def blueprint_registry(blueprint_registry_deployer):
    return blueprint_registry_deployer(["AMM", "CTR", "VLT", "CTRV"])


@pytest.fixture()
def get_allowed_ids():
    def f(blueprint_registry):
        ids = []
        for i in range(blueprint_registry.eval("MAX_LENGTH")):
            try:
                ids.append(blueprint_registry.eval(f"BLUEPRINT_REGISTRY_IDS[{i}]"))
            except Exception as e:
                break

        return ids

    return f
