"""Tests for AggMonetaryPolicy4.__init__ (constructor)"""

import pytest
import boa

from tests.utils.deployers import AGG_MONETARY_POLICY4_DEPLOYER
from tests.utils.constants import ZERO_ADDRESS

# Constants from the contract
MAX_TARGET_DEBT_FRACTION = 10**18
MAX_SIGMA = 10**18
MIN_SIGMA = 10**14
MAX_RATE = 43959106799  # 300% APY
MAX_EXTRA_CONST = MAX_RATE


def test_default_behavior(
    mp,
    admin,
    price_oracle,
    mock_factory,
    peg_keepers,
    default_rate,
    default_sigma,
    default_target_debt_fraction,
    default_extra_const,
    default_ema_time,
):
    """Default behavior: all parameters are set correctly."""
    assert mp.admin() == admin
    assert mp.PRICE_ORACLE() == price_oracle.address
    assert mp.CONTROLLER_FACTORY() == mock_factory.address
    assert mp.rate0() == default_rate
    assert mp.sigma() == default_sigma
    assert mp.target_debt_fraction() == default_target_debt_fraction
    assert mp.extra_const() == default_extra_const
    assert mp.debt_ratio_ema_time() == default_ema_time


def test_default_behavior_with_peg_keepers(mp, peg_keepers):
    """Peg keepers array is populated correctly."""
    for i, pk in enumerate(peg_keepers):
        assert mp.peg_keepers(i) == pk.address
    # Next slot should be empty
    assert mp.peg_keepers(len(peg_keepers)) == ZERO_ADDRESS


def test_default_behavior_partial_peg_keepers(
    admin,
    price_oracle,
    mock_factory,
    peg_keepers,
    default_rate,
    default_sigma,
    default_target_debt_fraction,
    default_extra_const,
    default_ema_time,
):
    """Constructor stops populating peg keepers at first empty address."""
    # Only pass first peg keeper, rest are empty
    pk_array = [peg_keepers[0].address] + [ZERO_ADDRESS] * 4

    with boa.env.prank(admin):
        mp = AGG_MONETARY_POLICY4_DEPLOYER.deploy(
            admin,
            price_oracle.address,
            mock_factory.address,
            pk_array,
            default_rate,
            default_sigma,
            default_target_debt_fraction,
            default_extra_const,
            default_ema_time,
        )

    assert mp.peg_keepers(0) == peg_keepers[0].address
    assert mp.peg_keepers(1) == ZERO_ADDRESS


def test_revert_sigma_too_low(
    admin,
    price_oracle,
    mock_factory,
    default_rate,
    default_target_debt_fraction,
    default_extra_const,
    default_ema_time,
):
    """Revert when sigma < MIN_SIGMA."""
    pk_array = [ZERO_ADDRESS] * 5

    with boa.env.prank(admin):
        with boa.reverts(dev="sigma too low"):
            AGG_MONETARY_POLICY4_DEPLOYER.deploy(
                admin,
                price_oracle.address,
                mock_factory.address,
                pk_array,
                default_rate,
                MIN_SIGMA - 1,  # Too low
                default_target_debt_fraction,
                default_extra_const,
                default_ema_time,
            )


def test_revert_sigma_too_high(
    admin,
    price_oracle,
    mock_factory,
    default_rate,
    default_target_debt_fraction,
    default_extra_const,
    default_ema_time,
):
    """Revert when sigma > MAX_SIGMA."""
    pk_array = [ZERO_ADDRESS] * 5

    with boa.env.prank(admin):
        with boa.reverts(dev="sigma too high"):
            AGG_MONETARY_POLICY4_DEPLOYER.deploy(
                admin,
                price_oracle.address,
                mock_factory.address,
                pk_array,
                default_rate,
                MAX_SIGMA + 1,  # Too high
                default_target_debt_fraction,
                default_extra_const,
                default_ema_time,
            )


def test_revert_target_debt_fraction_zero(
    admin,
    price_oracle,
    mock_factory,
    default_rate,
    default_sigma,
    default_extra_const,
    default_ema_time,
):
    """Revert when target_debt_fraction == 0."""
    pk_array = [ZERO_ADDRESS] * 5

    with boa.env.prank(admin):
        with boa.reverts(dev="target debt fraction is zero"):
            AGG_MONETARY_POLICY4_DEPLOYER.deploy(
                admin,
                price_oracle.address,
                mock_factory.address,
                pk_array,
                default_rate,
                default_sigma,
                0,  # Zero
                default_extra_const,
                default_ema_time,
            )


def test_revert_target_debt_fraction_too_high(
    admin,
    price_oracle,
    mock_factory,
    default_rate,
    default_sigma,
    default_extra_const,
    default_ema_time,
):
    """Revert when target_debt_fraction > MAX_TARGET_DEBT_FRACTION."""
    pk_array = [ZERO_ADDRESS] * 5

    with boa.env.prank(admin):
        with boa.reverts(dev="target debt fraction too high"):
            AGG_MONETARY_POLICY4_DEPLOYER.deploy(
                admin,
                price_oracle.address,
                mock_factory.address,
                pk_array,
                default_rate,
                default_sigma,
                MAX_TARGET_DEBT_FRACTION + 1,  # Too high
                default_extra_const,
                default_ema_time,
            )


def test_revert_rate_too_high(
    admin,
    price_oracle,
    mock_factory,
    default_sigma,
    default_target_debt_fraction,
    default_extra_const,
    default_ema_time,
):
    """Revert when rate > MAX_RATE."""
    pk_array = [ZERO_ADDRESS] * 5

    with boa.env.prank(admin):
        with boa.reverts(dev="rate too high"):
            AGG_MONETARY_POLICY4_DEPLOYER.deploy(
                admin,
                price_oracle.address,
                mock_factory.address,
                pk_array,
                MAX_RATE + 1,  # Too high
                default_sigma,
                default_target_debt_fraction,
                default_extra_const,
                default_ema_time,
            )


def test_revert_extra_const_too_high(
    admin,
    price_oracle,
    mock_factory,
    default_rate,
    default_sigma,
    default_target_debt_fraction,
    default_ema_time,
):
    """Revert when extra_const > MAX_EXTRA_CONST."""
    pk_array = [ZERO_ADDRESS] * 5

    with boa.env.prank(admin):
        with boa.reverts(dev="extra const too high"):
            AGG_MONETARY_POLICY4_DEPLOYER.deploy(
                admin,
                price_oracle.address,
                mock_factory.address,
                pk_array,
                default_rate,
                default_sigma,
                default_target_debt_fraction,
                MAX_EXTRA_CONST + 1,  # Too high
                default_ema_time,
            )
