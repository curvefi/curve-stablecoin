from tests.utils.constants import __version__


def test_default_behavior(controller):
    assert controller.version() == f"{__version__}-lend"
