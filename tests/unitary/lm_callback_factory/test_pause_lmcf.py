import boa

from tests.utils import filter_logs


def test_default_behavior(factory, owner):
    assert not factory.paused()

    factory.pause(sender=owner)

    assert factory.paused()


def test_pause_emits_event(factory, owner):
    factory.pause(sender=owner)

    logs = filter_logs(factory, "Paused")
    assert len(logs) == 1
    assert logs[0].account == owner


def test_unauthorized(factory, non_owner):
    with boa.reverts("ownable: caller is not the owner"):
        factory.pause(sender=non_owner)

    assert not factory.paused()


def test_pause_when_already_paused(paused_factory, owner):
    with boa.reverts("pausable: contract is paused"):
        paused_factory.pause(sender=owner)


def test_pause_leaves_the_registry_readable(factory, dummy_amm, owner):
    """Pausing only stops new deployments; everything already deployed stays queryable."""
    lm_callback = factory.deploy_lm_callback(dummy_amm)

    factory.pause(sender=owner)

    assert factory.is_valid_lm_callback(lm_callback)
    assert factory.get_lm_callback_count() == 1
    assert factory.get_lm_callback(0) == lm_callback
