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


def test_factory_resolves_the_callback_from_the_amm(
    lm_callback, lm_callback_factory, amm
):
    """The same round trip starting from the market instead of the callback."""
    assert lm_callback_factory.get_lm_callback_by_amm(amm.address) == (
        lm_callback.address
    )
    assert lm_callback.AMM() == amm.address


def test_callback_and_factory_report_versions(lm_callback, lm_callback_factory):
    assert lm_callback.version() == "1.0.0"
    assert lm_callback_factory.version() == "1.0.0"


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
