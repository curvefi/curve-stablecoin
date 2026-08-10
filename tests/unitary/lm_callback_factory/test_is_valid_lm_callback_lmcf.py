import boa

from tests.utils.constants import ZERO_ADDRESS
from tests.utils.deployers import DUMMY_LM_CALLBACK_DEPLOYER


def test_valid_for_deployed_callback(factory, dummy_amm):
    lm_callback = factory.deploy_lm_callback(dummy_amm)

    assert factory.is_valid_lm_callback(lm_callback)


def test_invalid_for_unknown_addresses(factory):
    assert not factory.is_valid_lm_callback(ZERO_ADDRESS)
    assert not factory.is_valid_lm_callback(boa.env.generate_address("stranger"))
    assert not factory.is_valid_lm_callback(factory.address)


def test_invalid_for_directly_deployed_callback(factory, dummy_amm):
    """Bypassing the factory means no registration, even for identical code."""
    lm_callback = DUMMY_LM_CALLBACK_DEPLOYER.deploy(dummy_amm)

    assert not factory.is_valid_lm_callback(lm_callback.address)


def test_invalid_across_factories(
    deploy_factory, owner, lm_callback_blueprint, dummy_amm
):
    """Each factory vouches only for its own deployments."""
    factory = deploy_factory(owner, lm_callback_blueprint)
    other_factory = deploy_factory(owner, lm_callback_blueprint)

    lm_callback = factory.deploy_lm_callback(dummy_amm)

    assert factory.is_valid_lm_callback(lm_callback)
    assert not other_factory.is_valid_lm_callback(lm_callback)


def test_stays_valid_after_blueprint_change(factory, dummy_amm, owner, other_blueprint):
    """
    Validity is never revoked: a callback from a superseded blueprint keeps
    vouching for itself after the owner has moved on to a new one.
    """
    lm_callback = factory.deploy_lm_callback(dummy_amm)

    factory.set_blueprint(other_blueprint, sender=owner)

    assert factory.is_valid_lm_callback(lm_callback)
