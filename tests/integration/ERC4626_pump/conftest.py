import boa
import pytest

from tests.utils.constants import MAX_UINT256
from tests.utils.deployers import (
    CRYPTO_FROM_ORACLE_AND_ERC4626_DEPLOYER,
    ORACLE_AND_EMA_ERC4626_DEPLOYER,
    DUMMY_PRICE_ORACLE_DEPLOYER,
)


# ---------------------------------------------------------------------------
# Dummy ERC4626 vault (inline).
#
# The CryptoFromOracleAndERC4626 oracle only reads `convertToAssets` from its
# VAULT.  We expose `set_share_price` so a test can instantaneously "pump" the
# share price (price per share) to manipulate the oracle.
# ---------------------------------------------------------------------------
DUMMY_VAULT_SOURCE = """
# pragma version 0.4.3

# price per share, scaled to 1e18 (1e18 == 1 asset per 1 share)
share_price: public(uint256)


@deploy
def __init__():
    self.share_price = 10**18


@external
@view
def convertToAssets(shares: uint256) -> uint256:
    return shares * self.share_price // 10**18


@external
def set_share_price(new_share_price: uint256):
    self.share_price = new_share_price
"""


# ---------------------------------------------------------------------------
# Market configuration – lending only, 18-decimal tokens, no borrow cap.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def market_type():
    return "lending"


@pytest.fixture(scope="module")
def borrowed_decimals():
    return 18


@pytest.fixture(scope="module")
def collateral_decimals():
    return 18


@pytest.fixture(scope="module")
def borrow_cap():
    return MAX_UINT256


@pytest.fixture(scope="module")
def seed_liquidity(borrowed_token):
    # Plenty of borrowed liquidity so the victim can borrow the maximum.
    return 10_000_000 * 10 ** borrowed_token.decimals()


@pytest.fixture(scope="module")
def initial_price():
    # ORACLE base price (collateral priced in the borrowed token).
    return 3000 * 10**18


# ---------------------------------------------------------------------------
# Oracle plumbing: CryptoFromOracleAndERC4626(ORACLE, VAULT)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def base_oracle(admin, initial_price):
    """Dummy ORACLE with a settable spot price."""
    return DUMMY_PRICE_ORACLE_DEPLOYER.deploy(admin, initial_price)


@pytest.fixture(scope="module")
def dummy_vault():
    """Inline dummy ERC4626 VAULT with a pumpable share price."""
    return boa.loads(DUMMY_VAULT_SOURCE)


@pytest.fixture(scope="module")
def price_oracle(base_oracle, dummy_vault):
    """Override the global price_oracle so the market is created with the
    CryptoFromOracleAndERC4626 oracle wrapping our dummy ORACLE + VAULT."""
    return CRYPTO_FROM_ORACLE_AND_ERC4626_DEPLOYER.deploy(
        base_oracle.address, dummy_vault.address
    )


# ---------------------------------------------------------------------------
# EMA-hardened oracle: OracleAndEMAERC4626(ORACLE, VAULT, ema_time).
#
# Wraps the *same* dummy ORACLE + VAULT but smooths the ERC4626 share price.
# A test swaps it onto the existing market via the Configurator to show an
# instantaneous share-price pump cannot force a liquidation.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ema_time():
    # Smoothing horizon of the share-price EMA (seconds).
    return 600


@pytest.fixture(scope="module")
def ema_oracle(base_oracle, dummy_vault, ema_time):
    return ORACLE_AND_EMA_ERC4626_DEPLOYER.deploy(
        base_oracle.address, dummy_vault.address, ema_time
    )
