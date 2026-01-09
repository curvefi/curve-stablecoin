from tests.utils.constants import __version__


def test_default_behavior(factory):
    assert factory.version() == __version__
