"""Fixtures for AggMonetaryPolicy4 unit tests."""

import pytest
import boa

from tests.utils.deployers import (
    AGG_MONETARY_POLICY4_DEPLOYER,
    MOCK_FACTORY_DEPLOYER,
    MOCK_PEG_KEEPER_DEPLOYER,
    DUMMY_PRICE_ORACLE_DEPLOYER,
)
from tests.utils.constants import ZERO_ADDRESS

# Constants from the contract
MAX_TARGET_DEBT_FRACTION = 10**18
MAX_SIGMA = 10**18
MIN_SIGMA = 10**14
MAX_EXP = 1000 * 10**18
MAX_RATE = 43959106799  # 300% APY
TARGET_REMAINDER = 10**17
MAX_EXTRA_CONST = MAX_RATE
DEBT_CANDLE_TIME = 86400 // 2  # 12 hours


@pytest.fixture(scope="module")
def admin():
    return boa.env.generate_address("admin")


@pytest.fixture(scope="module")
def price_oracle(admin):
    """Deploy a mock price oracle with price = 1e18 (peg)."""
    with boa.env.prank(admin):
        return DUMMY_PRICE_ORACLE_DEPLOYER.deploy(admin, 10**18)


@pytest.fixture(scope="module")
def mock_factory():
    """Deploy a mock controller factory."""
    return MOCK_FACTORY_DEPLOYER.deploy()


@pytest.fixture(scope="module")
def peg_keepers():
    """Deploy 3 mock peg keepers with zero debt."""
    keepers = []
    for i in range(3):
        # MockPegKeeper(price, stablecoin) - we don't need real stablecoin for tests
        pk = MOCK_PEG_KEEPER_DEPLOYER.deploy(10**18, boa.env.generate_address(f"stablecoin_{i}"))
        keepers.append(pk)
    return keepers


@pytest.fixture(scope="module")
def deployer():
    """Return the AggMonetaryPolicy4 deployer for direct deployment in tests."""
    return AGG_MONETARY_POLICY4_DEPLOYER


@pytest.fixture(scope="module")
def default_rate():
    """Default base rate (~2% APY)."""
    return 634195839


@pytest.fixture(scope="module")
def default_sigma():
    """Default sigma value."""
    return 2 * 10**16


@pytest.fixture(scope="module")
def default_target_debt_fraction():
    """Default target debt fraction (10%)."""
    return 10**17


@pytest.fixture(scope="module")
def default_extra_const():
    """Default extra constant (0)."""
    return 0


@pytest.fixture(scope="module")
def default_ema_time():
    """Default EMA time (1 day)."""
    return 86400


@pytest.fixture(scope="module")
def mp(
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
    """Deploy AggMonetaryPolicy4 with default parameters."""
    # Create peg keeper array with padding to 5 elements
    pk_array = [pk.address for pk in peg_keepers] + [ZERO_ADDRESS] * (5 - len(peg_keepers))

    with boa.env.prank(admin):
        return AGG_MONETARY_POLICY4_DEPLOYER.deploy(
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


@pytest.fixture(scope="module")
def mp_no_peg_keepers(
    admin,
    price_oracle,
    mock_factory,
    default_rate,
    default_sigma,
    default_target_debt_fraction,
    default_extra_const,
    default_ema_time,
):
    """Deploy AggMonetaryPolicy4 without peg keepers."""
    pk_array = [ZERO_ADDRESS] * 5

    with boa.env.prank(admin):
        return AGG_MONETARY_POLICY4_DEPLOYER.deploy(
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
