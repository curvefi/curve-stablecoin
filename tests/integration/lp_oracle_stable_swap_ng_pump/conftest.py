import boa
import pytest

from tests.utils.constants import MAX_UINT256
from tests.utils.deployers import (
    LP_ORACLE_STABLESWAP_NG_DEPLOYER,
    STABLESWAP_NG_SPOT_LP_ORACLE_DEPLOYER,
)


# ---------------------------------------------------------------------------
# Dummy StableSwap-NG pool (inline).
#
# The LP oracles only read `A_precise`, `price_oracle(i)`, `get_virtual_price`
# and `coins(i)` from the pool.  We expose `set_virtual_price` so a test can
# instantaneously "pump" the virtual price (D per LP token) to manipulate the
# oracle, mirroring what wash trading or a misbehaving coin rate oracle does on
# a real pool.
#
# `coins(2)` must revert: LPOracle._sanity_check probes it to reject pools with
# more than 2 coins.
# ---------------------------------------------------------------------------
DUMMY_POOL_SOURCE = """
# pragma version 0.4.3

N_COINS: constant(uint256) = 2

# A_true * N_COINS**(N_COINS-1) * 100, exactly as a real pool stores it
A_precise: public(uint256)
# D per LP token, scaled to 1e18 (1e18 == pool has not accrued anything yet)
get_virtual_price: public(uint256)

_price_oracle: uint256


@deploy
def __init__(_a_precise: uint256, _price: uint256, _virtual_price: uint256):
    self.A_precise = _a_precise
    self._price_oracle = _price
    self.get_virtual_price = _virtual_price


@external
@view
def coins(i: uint256) -> address:
    assert i < N_COINS  # a 3-coin pool would answer coins(2)
    return empty(address)  # the oracles never touch the coins themselves


@external
@view
def price_oracle(i: uint256) -> uint256:
    assert i + 1 < N_COINS  # valid indices are 0 .. n_coins-2, like real pools
    return self._price_oracle


@external
def set_virtual_price(_virtual_price: uint256):
    self.get_virtual_price = _virtual_price
"""


DUMMY_POOL_DEPLOYER = boa.loads_partial(DUMMY_POOL_SOURCE)


# ---------------------------------------------------------------------------
# Market configuration - lending only, 18-decimal tokens, no borrow cap.
#
# The collateral token is a plain mock ERC20 standing in for the pool's LP
# token: neither oracle ever touches the LP token itself, only the pool.
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


# ---------------------------------------------------------------------------
# Pool parameters.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pool_A_precise():
    # A = 100 stored the way a 2-coin pool stores it: A * N**(N-1) * 100.
    return 100 * 2 * 100


@pytest.fixture(scope="module")
def pool_price():
    # price_oracle(0): coins are at parity.
    return 10**18


@pytest.fixture(scope="module")
def coin_idx():
    # Numeraire: the LP price is quoted in the base asset of coins(0).
    return 0


@pytest.fixture(scope="module")
def pool(pool_A_precise, pool_price):
    """Inline dummy StableSwap-NG pool with a pumpable virtual price."""
    return DUMMY_POOL_DEPLOYER.deploy(pool_A_precise, pool_price, 10**18)


# ---------------------------------------------------------------------------
# Oracle plumbing: StableSwapNGLPOracle(POOL, COIN_IDX, ema_time) prices the
# pool while smoothing its manipulable virtual price.  The market is created
# with it directly.
#
# `spot_lp_oracle` is the upstream stateless helper the hardened oracle is built
# on; tests use it as the un-dampened reference price.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ema_time():
    # Smoothing horizon of the virtual-price EMA (seconds).
    return 600


@pytest.fixture(scope="module")
def spot_lp_oracle():
    """Upstream stateless LP oracle: lp_price(pool, i) off the spot virtual price."""
    return STABLESWAP_NG_SPOT_LP_ORACLE_DEPLOYER.deploy()


@pytest.fixture(scope="module")
def price_oracle(pool, coin_idx, ema_time):
    """Override the global price_oracle so the market is created with the
    EMA-hardened LP oracle."""
    return LP_ORACLE_STABLESWAP_NG_DEPLOYER.deploy(pool.address, coin_idx, ema_time)
