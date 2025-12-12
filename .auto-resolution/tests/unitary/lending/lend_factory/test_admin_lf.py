def test_default_behavior(factory, admin):
    assert factory.admin() == admin
