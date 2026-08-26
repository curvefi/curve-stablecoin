import boa

from tests.utils.constants import ZERO_ADDRESS
from tests.utils.deployers import DUMMY_LM_CALLBACK_DEPLOYER


def test_records_the_deployed_callback(factory, dummy_amm):
    lm_callback = factory.deploy_lm_callback(dummy_amm)

    assert factory.get_lm_callback_by_amm(dummy_amm) == lm_callback


def test_zero_for_unknown_amms(factory, dummy_amm):
    assert factory.get_lm_callback_by_amm(dummy_amm) == ZERO_ADDRESS
    assert factory.get_lm_callback_by_amm(ZERO_ADDRESS) == ZERO_ADDRESS
    assert factory.get_lm_callback_by_amm(boa.env.generate_address("amm")) == (
        ZERO_ADDRESS
    )


def test_zero_for_directly_deployed_callback(factory, dummy_amm):
    """Bypassing the factory means no registration, even for identical code."""
    DUMMY_LM_CALLBACK_DEPLOYER.deploy(dummy_amm)

    assert factory.get_lm_callback_by_amm(dummy_amm) == ZERO_ADDRESS


def test_each_amm_tracked_separately(factory):
    amms = [boa.env.generate_address(f"amm_{i}") for i in range(3)]

    lm_callbacks = [factory.deploy_lm_callback(amm) for amm in amms]

    for amm, lm_callback in zip(amms, lm_callbacks):
        assert factory.get_lm_callback_by_amm(amm) == lm_callback


def test_newest_callback_wins(factory, dummy_amm, owner, other_blueprint):
    """A redeploy after a blueprint rotation supersedes the earlier entry."""
    first = factory.deploy_lm_callback(dummy_amm)

    factory.set_blueprint(other_blueprint, sender=owner)
    second = factory.deploy_lm_callback(dummy_amm)

    assert factory.get_lm_callback_by_amm(dummy_amm) == second
    assert factory.get_lm_callback_by_amm(dummy_amm) != first


def test_tracked_per_factory(deploy_factory, owner, lm_callback_blueprint, dummy_amm):
    """Each factory records only its own deployments."""
    factory = deploy_factory(owner, lm_callback_blueprint)
    other_factory = deploy_factory(owner, lm_callback_blueprint)

    lm_callback = factory.deploy_lm_callback(dummy_amm)

    assert factory.get_lm_callback_by_amm(dummy_amm) == lm_callback
    assert other_factory.get_lm_callback_by_amm(dummy_amm) == ZERO_ADDRESS
