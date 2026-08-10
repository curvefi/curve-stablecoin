import boa

from tests.utils import filter_logs
from tests.utils.constants import ZERO_ADDRESS


def test_ctor(deploy_factory, owner, lm_callback_blueprint):
    factory = deploy_factory(owner, lm_callback_blueprint)

    assert factory.owner() == owner
    assert factory.lm_callback_blueprint() == lm_callback_blueprint.address
    assert not factory.paused()
    assert factory.get_lm_callback_count() == 0


def test_ctor_emits_blueprint_event(deploy_factory, owner, lm_callback_blueprint):
    factory = deploy_factory(owner, lm_callback_blueprint)

    logs = filter_logs(factory, "UpdateLMCallbackBlueprint")
    assert len(logs) == 1
    assert logs[0].old_blueprint == ZERO_ADDRESS
    assert logs[0].new_blueprint == lm_callback_blueprint.address


def test_ctor_transfers_ownership_away_from_deployer(
    deploy_factory, owner, lm_callback_blueprint
):
    deployer = boa.env.generate_address("deployer")
    with boa.env.prank(deployer):
        factory = deploy_factory(owner, lm_callback_blueprint)

    # `ownable.__init__` seats the deployer first, so ownership lands on `_owner`
    # only via the transfer that follows it
    logs = filter_logs(factory, "OwnershipTransferred")
    assert [(log.previous_owner, log.new_owner) for log in logs] == [
        (ZERO_ADDRESS, deployer),
        (deployer, owner),
    ]
    assert factory.owner() == owner


def test_ctor_reverts_if_owner_is_zero(deploy_factory, lm_callback_blueprint):
    with boa.reverts():
        deploy_factory(ZERO_ADDRESS, lm_callback_blueprint)


def test_ctor_reverts_if_blueprint_is_zero(deploy_factory, owner):
    with boa.reverts():
        deploy_factory(owner, ZERO_ADDRESS)
