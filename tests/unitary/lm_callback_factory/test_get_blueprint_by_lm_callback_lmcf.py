import boa

from tests.utils.constants import ZERO_ADDRESS
from tests.utils.deployers import DUMMY_LM_CALLBACK_DEPLOYER


def test_records_the_blueprint_used(factory, dummy_amm, lm_callback_blueprint):
    lm_callback = factory.deploy_lm_callback(dummy_amm)

    assert (
        factory.get_blueprint_by_lm_callback(lm_callback)
        == lm_callback_blueprint.address
    )


def test_zero_for_unknown_addresses(factory):
    assert factory.get_blueprint_by_lm_callback(ZERO_ADDRESS) == ZERO_ADDRESS
    assert factory.get_blueprint_by_lm_callback(factory.address) == ZERO_ADDRESS
    assert (
        factory.get_blueprint_by_lm_callback(boa.env.generate_address("stranger"))
        == ZERO_ADDRESS
    )


def test_zero_for_directly_deployed_callback(factory, dummy_amm):
    """Bypassing the factory means no registration, even for identical code."""
    lm_callback = DUMMY_LM_CALLBACK_DEPLOYER.deploy(dummy_amm)

    assert factory.get_blueprint_by_lm_callback(lm_callback.address) == ZERO_ADDRESS


def test_records_the_blueprint_current_at_deploy_time(
    factory, dummy_amm, owner, lm_callback_blueprint, other_blueprint
):
    """
    Each callback keeps pointing at the blueprint it was created from, so a
    rotation never rewrites the provenance of earlier deployments.
    """
    first = factory.deploy_lm_callback(dummy_amm)

    factory.set_blueprint(other_blueprint, sender=owner)
    second = factory.deploy_lm_callback(dummy_amm)

    assert factory.get_blueprint_by_lm_callback(first) == lm_callback_blueprint.address
    assert factory.get_blueprint_by_lm_callback(second) == other_blueprint.address
