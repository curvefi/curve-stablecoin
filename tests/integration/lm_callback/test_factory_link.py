"""
The `factory()` / `is_valid_gauge()` round trip that the gauge convention exists
for: integrations start from a factory they trust and check that it and the
callback point at each other.
"""

import boa

from tests.utils.deployers import LM_CALLBACK_DEPLOYER


def test_callback_points_back_at_its_factory(lm_callback, lm_callback_factory):
    assert lm_callback.factory() == lm_callback_factory.address


def test_factory_vouches_for_its_callback(lm_callback, lm_callback_factory):
    assert lm_callback_factory.is_valid_gauge(lm_callback.address)


def test_direct_deployment_records_its_deployer(amm, lm_callback_factory):
    """
    Deploying outside a factory is not blocked, it just leaves `factory()`
    pointing at the deployer - which no factory vouches for.
    """
    deployer = boa.env.generate_address("deployer")
    with boa.env.prank(deployer):
        lm_callback = LM_CALLBACK_DEPLOYER.deploy(amm)

    assert lm_callback.factory() == deployer
    assert not lm_callback_factory.is_valid_gauge(lm_callback.address)
