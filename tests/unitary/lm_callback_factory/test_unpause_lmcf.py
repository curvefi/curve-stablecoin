import boa

from tests.utils import filter_logs


def test_default_behavior(paused_factory, owner):
    assert paused_factory.paused()

    paused_factory.unpause(sender=owner)

    assert not paused_factory.paused()


def test_unpause_emits_event(paused_factory, owner):
    paused_factory.unpause(sender=owner)

    logs = filter_logs(paused_factory, "Unpaused")
    assert len(logs) == 1
    assert logs[0].account == owner


def test_unauthorized(paused_factory, non_owner):
    with boa.reverts("ownable: caller is not the owner"):
        paused_factory.unpause(sender=non_owner)

    assert paused_factory.paused()


def test_unpause_when_not_paused(factory, owner):
    with boa.reverts("pausable: contract is not paused"):
        factory.unpause(sender=owner)


def test_pause_cycle(factory, owner, dummy_amm):
    factory.pause(sender=owner)
    factory.unpause(sender=owner)
    factory.pause(sender=owner)
    factory.unpause(sender=owner)

    assert not factory.paused()
    assert factory.is_valid_lm_callback(factory.deploy_lm_callback(dummy_amm))
