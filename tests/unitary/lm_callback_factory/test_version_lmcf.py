def test_default_behavior(factory):
    """
    Versioned independently of the core contracts, so this is a literal rather
    than `tests.utils.constants.__version__`.
    """
    assert factory.version() == "1.0.0"
