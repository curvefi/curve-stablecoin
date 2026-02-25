"""
Test that NO_ARGUMENT detection works with old Vyper (<0.3.3) 2-coin pools.

Old Vyper pools execute STOP (not REVERT) for unknown function selectors,
returning success=True with empty returndata. Without the len(res) < 32 check,
these pools get misclassified as supporting price_oracle(uint256).

Pool used: WETH/CVX (0xB576491F...), compiled with Vyper 0.3.1.
- Has price_oracle() (0x86fc88d3) but NOT price_oracle(uint256) (0x68727653).
"""

import boa
import pytest
from eth_abi import encode


# WETH/CVX CryptoSwap pool (Vyper 0.3.1) — only has price_oracle(), no price_oracle(uint256)
WETH_CVX_POOL = "0xB576491F1E6e5E62f1d8F26062Ee822B40B0E0d4"

# TriCRV pool (Vyper 0.3.7+) — has price_oracle(uint256), used as second pool in chain
TRICRV_POOL = "0x4eBdF703948ddCEA3B11f675B4D1Fba9d2414A14"

# Function selectors
PRICE_ORACLE_UINT256 = bytes.fromhex("68727653")  # price_oracle(uint256)
PRICE_ORACLE_NO_ARG = bytes.fromhex("86fc88d3")   # price_oracle()


def test_old_vyper_pool_returns_empty_data_on_unknown_selector():
    """Old Vyper pool returns success=True with empty data for price_oracle(uint256).

    This is the root cause: Vyper <0.3.3 executes STOP (not REVERT) for unknown
    selectors, so success=True but returndata is empty. Checking only `success`
    misclassifies the pool as supporting price_oracle(uint256).
    """
    calldata = PRICE_ORACLE_UINT256 + encode(["uint256"], [0])

    # price_oracle(uint256) — pool doesn't have this function
    result = boa.env.raw_call(WETH_CVX_POOL, data=calldata)
    assert result.is_success is True
    assert len(result.output) == 0  # STOP: success but empty returndata

    # price_oracle() — pool has this function
    result = boa.env.raw_call(WETH_CVX_POOL, data=PRICE_ORACLE_NO_ARG)
    assert result.is_success is True
    assert len(result.output) == 32  # returns a proper uint256


def test_new_vyper_pool_reverts_on_unknown_selector():
    """New Vyper pool (0.3.7+) properly reverts for price_oracle(uint256) with bad index."""
    calldata = PRICE_ORACLE_UINT256 + encode(["uint256"], [99])

    with pytest.raises(Exception):  # REVERT: new Vyper properly rejects bad input
        boa.env.raw_call(TRICRV_POOL, data=calldata)


def test_crypto_from_pool_with_old_vyper_pool():
    """CryptoFromPool deploys and returns correct price with old Vyper 2-coin pool."""
    oracle = boa.load(
        "curve_stablecoin/price_oracles/CryptoFromPool.vy",
        WETH_CVX_POOL,
        2,  # N (2-coin pool)
        0,  # borrowed_ix (WETH)
        1,  # collateral_ix (CVX)
    )
    assert oracle.NO_ARGUMENT() is True
    price = oracle.price()
    assert price > 0


def test_crypto_from_pools_rate_with_old_vyper_pool():
    """CryptoFromPoolsRate chains through old Vyper pool and returns correct price."""
    oracle = boa.load(
        "curve_stablecoin/price_oracles/CryptoFromPoolsRate.vy",
        [WETH_CVX_POOL, TRICRV_POOL],
        [0, 0],  # borrowed_ixs
        [1, 1],  # collateral_ixs
    )
    assert oracle.NO_ARGUMENT(0) is True
    assert oracle.NO_ARGUMENT(1) is False
    price = oracle.price()
    assert price > 0
