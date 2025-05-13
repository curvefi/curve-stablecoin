# @version 0.3.10
"""
@title CryptoFromPoolsVaultWAgg
@notice Price oracle for chained pools (up to 8) combining crypto/crvUSD pricing and vault redemption rate.
        It also references aggregated USD, so works for mint markets.
        Only suitable for vaults which cannot be affected by donation attack (like sFRAX).
        Ensure vault and underlying are 18 decimals.
@author Curve.Fi
@license MIT
"""

MAX_COINS: constant(uint256) = 8
MAX_POOLS: constant(uint256) = 8

interface Pool:
    def price_oracle(i: uint256 = 0) -> uint256: view
    def coins(i: uint256) -> address: view

interface StableAggregator:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable
    def stablecoin() -> address: view

interface Vault:
    def convertToAssets(shares: uint256) -> uint256: view

POOLS: public(immutable(DynArray[Pool, MAX_POOLS]))
BORROWED_IX: public(immutable(DynArray[uint256, MAX_POOLS]))
COLLATERAL_IX: public(immutable(DynArray[uint256, MAX_POOLS]))
NO_ARGUMENT: public(immutable(DynArray[bool, MAX_POOLS]))
POOL_COUNT: public(immutable(uint256))
VAULT: public(immutable(Vault))
AGG: public(immutable(StableAggregator))

@external
def __init__(
        pools: DynArray[Pool, MAX_POOLS],
        borrowed_ixs: DynArray[uint256, MAX_POOLS],
        collateral_ixs: DynArray[uint256, MAX_POOLS],
        vault: Vault,
        agg: StableAggregator
    ):
    POOLS = pools
    pool_count: uint256 = 0
    no_arguments: DynArray[bool, MAX_POOLS] = empty(DynArray[bool, MAX_POOLS])

    for i in range(MAX_POOLS):
        if i == len(pools):
            assert i != 0, "Wrong pool counts"
            pool_count = i
            break

        # Find N
        N: uint256 = 0
        for j in range(MAX_COINS + 1):
            success: bool = False
            res: Bytes[32] = empty(Bytes[32])
            success, res = raw_call(
                pools[i].address,
                _abi_encode(j, method_id=method_id("coins(uint256)")),
                max_outsize=32, is_static_call=True, revert_on_failure=False)
            if not success:
                assert j != 0, "No coins(0)"
                N = j
                break    

        assert borrowed_ixs[i] != collateral_ixs[i]
        assert borrowed_ixs[i] < N
        assert collateral_ixs[i] < N

        # Init variables for raw call
        success: bool = False

        # Check and record if pool requires coin id in argument or no
        if N == 2:
            res: Bytes[32] = empty(Bytes[32])
            success, res = raw_call(
                pools[i].address,
                _abi_encode(empty(uint256), method_id=method_id("price_oracle(uint256)")),
                max_outsize=32, is_static_call=True, revert_on_failure=False)
            if not success:
                no_arguments.append(True)
            else:
                no_arguments.append(False)
        else:
            no_arguments.append(False)

    NO_ARGUMENT = no_arguments
    BORROWED_IX = borrowed_ixs
    COLLATERAL_IX = collateral_ixs
    if pool_count == 0:
        pool_count = MAX_POOLS
    POOL_COUNT = pool_count
    VAULT = vault
    AGG = agg

@internal
@view
def _raw_price() -> uint256:
    _price: uint256 = 10**18
    for i in range(MAX_POOLS):
        if i >= POOL_COUNT:
            break
        p_borrowed: uint256 = 10**18
        p_collateral: uint256 = 10**18

        if NO_ARGUMENT[i]:
            p: uint256 = POOLS[i].price_oracle()
            if COLLATERAL_IX[i] > 0:
                p_collateral = p
            else:
                p_borrowed = p

        else:
            if BORROWED_IX[i] > 0:
                p_borrowed = POOLS[i].price_oracle(unsafe_sub(BORROWED_IX[i], 1))
            if COLLATERAL_IX[i] > 0:
                p_collateral = POOLS[i].price_oracle(unsafe_sub(COLLATERAL_IX[i], 1))
        _price = _price * p_collateral / p_borrowed
    return _price * VAULT.convertToAssets(10**18)

@external
@view
def price() -> uint256:
    return self._raw_price() * AGG.price() / 10**36

@external
def price_w() -> uint256:
    return self._raw_price() * AGG.price_w() / 10**36
