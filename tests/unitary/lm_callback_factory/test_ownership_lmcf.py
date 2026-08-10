import boa

from tests.utils import filter_logs
from tests.utils.constants import ZERO_ADDRESS


def test_owner(factory, owner):
    assert factory.owner() == owner


def test_transfer_ownership(factory, owner):
    new_owner = boa.env.generate_address("new_owner")

    factory.transfer_ownership(new_owner, sender=owner)

    assert factory.owner() == new_owner


def test_transfer_ownership_emits_event(factory, owner):
    new_owner = boa.env.generate_address("new_owner")

    factory.transfer_ownership(new_owner, sender=owner)

    logs = filter_logs(factory, "OwnershipTransferred")
    assert len(logs) == 1
    assert logs[0].previous_owner == owner
    assert logs[0].new_owner == new_owner


def test_transfer_ownership_unauthorized(factory, owner, non_owner):
    with boa.reverts("ownable: caller is not the owner"):
        factory.transfer_ownership(non_owner, sender=non_owner)

    assert factory.owner() == owner


def test_transfer_ownership_to_zero_reverts(factory, owner):
    """
    The owner cannot be dropped: `LMCallback.set_killed` is gated on it, and an
    ownerless factory could never update or unset its blueprint again.
    """
    with boa.reverts("ownable: new owner is the zero address"):
        factory.transfer_ownership(ZERO_ADDRESS, sender=owner)

    assert factory.owner() == owner


def test_renounce_ownership_is_not_exported(factory):
    assert not hasattr(factory, "renounce_ownership")


def test_new_owner_takes_over_admin_rights(factory, owner):
    new_owner = boa.env.generate_address("new_owner")
    factory.transfer_ownership(new_owner, sender=owner)

    factory.pause(sender=new_owner)
    assert factory.paused()

    with boa.reverts("ownable: caller is not the owner"):
        factory.unpause(sender=owner)
    factory.unpause(sender=new_owner)

    new_blueprint = boa.env.generate_address("new_blueprint")
    factory.set_blueprint(new_blueprint, sender=new_owner)
    assert factory.lm_callback_blueprint() == new_blueprint
