import pytest

from tests.utils import filter_logs
from tests.utils.deployers import CONFIGURATOR_DEPLOYER


@pytest.fixture
def deploy_standalone_configurator():
    def _deploy_standalone_configurator(default_admin):
        return CONFIGURATOR_DEPLOYER.deploy(default_admin)

    return _deploy_standalone_configurator


@pytest.fixture
def get_controller_admin():
    def _get_controller_admin(configurator, controller):
        return configurator.eval(f"self.admins[IController({controller})]")

    return _get_controller_admin


@pytest.fixture
def single_configurator_event():
    def _single_configurator_event(configurator, event_name):
        logs = filter_logs(configurator, event_name)
        assert len(logs) == 1
        return logs[0]

    return _single_configurator_event
