import boa


def test_default_behavior(factory, admin):
    assert not factory.paused()

    with boa.env.prank(admin):
        factory.pause()

    assert factory.paused()


def test_unauthorized(factory, alice):
    with boa.reverts("ownable: caller is not the owner"):
        with boa.env.prank(alice):
            factory.pause()
