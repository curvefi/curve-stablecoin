import boa
import pytest

from tests.utils.deployers import ORACLE_FROM_CURVE_POOLS_DEPLOYER

ONE = 10**18


# ---------------------------------------------------------------------------
# Inline mock pools.
#
# The oracle only touches price_oracle(...) on each pool, the "universal" price
# method. Curve pools come in two shapes for it, which the oracle detects (by
# probing price_oracle(uint256)) and stores as the per-pool NO_ARGUMENT flag:
#   * ArgPool   - price_oracle(uint256): stableswap-ng / tricrypto style.  The
#                 probe succeeds -> NO_ARGUMENT = False. Reverts on an
#                 out-of-range index, like a real pool.
#   * NoArgPool - price_oracle():        old 2-coin plain-pool style.  The oracle
#                 probes price_oracle(uint256), the call fails (no such selector)
#                 -> NO_ARGUMENT = True.
# ---------------------------------------------------------------------------

# price_oracle(i) returns a preconfigured value per valid index.
ARG_POOL_SOURCE = """
# pragma version 0.4.3

n_coins: public(uint256)
prices: public(HashMap[uint256, uint256])

@deploy
def __init__(n: uint256, prices: DynArray[uint256, 8]):
    self.n_coins = n
    for i: uint256 in range(len(prices), bound=8):
        self.prices[i] = prices[i]

@external
@view
def price_oracle(i: uint256) -> uint256:
    assert i + 1 < self.n_coins  # valid indices are 0 .. n_coins-2, like real pools
    return self.prices[i]
"""

# 2-coin pool exposing only the argument-less price_oracle(). It intentionally
# does NOT implement price_oracle(uint256), so the oracle classifies it as
# NO_ARGUMENT = True.
NOARG_POOL_SOURCE = """
# pragma version 0.4.3

oracle_price: public(uint256)

@deploy
def __init__(price: uint256):
    self.oracle_price = price

@external
@view
def price_oracle() -> uint256:
    return self.oracle_price
"""

# A 2-coin crypto pool as actually deployed by *old* Curve pools that hold
# native ETH: compiled with Vyper 0.3.1, exposing only the argument-less
# price_oracle(), plus a payable __default__() so the pool can receive ETH.
#
# The fallback is the tricky case for NO_ARGUMENT detection. Probing the
# (nonexistent) price_oracle(uint256) selector does NOT revert -- it lands in
# __default__ and STOPs, returning success with *empty* returndata. So a probe
# that checks only `success` would misclassify this no-argument pool as one that
# takes an index argument; the oracle must also require non-empty returndata.
# (The compiler version is incidental: any pool with a non-reverting fallback
# behaves this way; real old ETH pools happen to be 0.3.x.)
OLD_ETH_POOL_SOURCE = """
# @version 0.3.1

oracle_price: public(uint256)

@external
def __init__(price: uint256):
    self.oracle_price = price

@external
@view
def price_oracle() -> uint256:
    return self.oracle_price

@external
@payable
def __default__():
    pass  # receive ETH; also swallows unknown selectors -> STOP, empty returndata
"""

ARG_POOL_DEPLOYER = boa.loads_partial(ARG_POOL_SOURCE)
NOARG_POOL_DEPLOYER = boa.loads_partial(NOARG_POOL_SOURCE)
OLD_ETH_POOL_DEPLOYER = boa.loads_partial(OLD_ETH_POOL_SOURCE)


# ---------------------------------------------------------------------------
# Factories.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def make_arg_pool():
    """Deploy an N-coin pool with price_oracle(uint256).

    prices[k] is the value returned by price_oracle(k) (price of coins(k+1)
    denominated in coins(0)).
    """

    def _make(n, prices):
        return ARG_POOL_DEPLOYER.deploy(n, prices)

    return _make


@pytest.fixture(scope="module")
def make_noarg_pool():
    """Deploy a 2-coin pool exposing only price_oracle() (no argument)."""

    def _make(price):
        return NOARG_POOL_DEPLOYER.deploy(price)

    return _make


@pytest.fixture(scope="module")
def make_old_eth_pool():
    """Deploy a real Vyper 0.3.1 2-coin pool: no-arg price_oracle() plus a
    payable __default__() (as ETH-holding crypto pools have). The fallback makes
    a price_oracle(uint256) probe STOP (success, empty returndata) instead of
    reverting -- the condition that breaks a success-only NO_ARGUMENT probe."""

    def _make(price):
        return OLD_ETH_POOL_DEPLOYER.deploy(price)

    return _make


@pytest.fixture(scope="module")
def deploy_oracle():
    """Deploy OracleFromCurvePools over the given pools / index config.

    pools:          list of mock pool contracts
    borrowed_ixs:   coin index of the borrowed token in each pool
    collateral_ixs: coin index of the collateral token in each pool
    """

    def _deploy(pools, borrowed_ixs, collateral_ixs):
        return ORACLE_FROM_CURVE_POOLS_DEPLOYER.deploy(
            [p.address for p in pools], borrowed_ixs, collateral_ixs
        )

    return _deploy
