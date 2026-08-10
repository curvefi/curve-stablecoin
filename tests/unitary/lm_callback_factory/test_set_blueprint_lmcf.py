import boa

from tests.utils.constants import ZERO_ADDRESS


def test_set_blueprint(factory, owner):
    new_blueprint = boa.env.generate_address("new_blueprint")

    factory.set_blueprint(new_blueprint, sender=owner)

    assert factory.lm_callback_blueprint() == new_blueprint


def test_set_blueprint_emits_event(
    factory, owner, lm_callback_blueprint, single_factory_event
):
    new_blueprint = boa.env.generate_address("new_blueprint")

    factory.set_blueprint(new_blueprint, sender=owner)

    log = single_factory_event(factory, "UpdateLMCallbackBlueprint")
    assert log.old_blueprint == lm_callback_blueprint.address
    assert log.new_blueprint == new_blueprint


def test_set_blueprint_emits_event_even_when_unchanged(
    factory, owner, lm_callback_blueprint, single_factory_event
):
    factory.set_blueprint(lm_callback_blueprint, sender=owner)

    log = single_factory_event(factory, "UpdateLMCallbackBlueprint")
    assert log.old_blueprint == log.new_blueprint == lm_callback_blueprint.address


def test_set_blueprint_unauthorized(factory, non_owner, lm_callback_blueprint):
    with boa.reverts("ownable: caller is not the owner"):
        factory.set_blueprint(boa.env.generate_address("new"), sender=non_owner)

    assert factory.lm_callback_blueprint() == lm_callback_blueprint.address


def test_set_blueprint_reverts_on_zero(factory, owner, lm_callback_blueprint):
    """
    The blueprint cannot be unset, so deployments can never be disabled this way -
    pausing is the only way to halt them.
    """
    with boa.reverts():
        factory.set_blueprint(ZERO_ADDRESS, sender=owner)

    assert factory.lm_callback_blueprint() == lm_callback_blueprint.address


def test_blueprint_is_never_zero(factory, owner, other_blueprint, dummy_amm):
    """
    Guarded on both write paths - constructor and setter - which is why
    `deploy_lm_callback` carries no unset-blueprint check of its own.
    """
    assert factory.lm_callback_blueprint() != ZERO_ADDRESS

    factory.set_blueprint(other_blueprint, sender=owner)

    assert factory.lm_callback_blueprint() != ZERO_ADDRESS
    assert factory.is_valid_lm_callback(factory.deploy_lm_callback(dummy_amm))


def test_new_blueprint_is_used_for_later_deployments(
    factory, owner, dummy_amm, other_blueprint
):
    from_old_blueprint = factory.deploy_lm_callback(dummy_amm)

    factory.set_blueprint(other_blueprint, sender=owner)
    from_new_blueprint = factory.deploy_lm_callback(dummy_amm)

    assert boa.env.get_code(from_new_blueprint) != boa.env.get_code(from_old_blueprint)
    assert factory.is_valid_lm_callback(from_old_blueprint)
    assert factory.is_valid_lm_callback(from_new_blueprint)


def test_event_reports_the_blueprint_a_deployment_used(
    factory, owner, dummy_amm, other_blueprint, single_factory_event
):
    factory.set_blueprint(other_blueprint, sender=owner)

    factory.deploy_lm_callback(dummy_amm)

    log = single_factory_event(factory, "DeployedLMCallback")
    assert log.blueprint == other_blueprint.address
