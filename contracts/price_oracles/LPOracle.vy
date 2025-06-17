# @version 0.4.1
#pragma optimize gas
#pragma evm-version shanghai

"""
@title LPOracle
@author Curve.Fi
@license GNU Affero General Public License v3.0 only
@notice Price oracle for Curve pool LPs. First, the oracle gets LP token price in terms of the first coin (coin0) of the pool.
        Then it chains with another oracle (target_coin/coin0) to get the final price.
"""

from ethereum.ercs import IERC20Detailed


interface Pool:
    def coins(i: uint256) -> address: view
    def price_oracle(i: uint256 = 0) -> uint256: view  # Universal method!
    def stored_rates() -> DynArray[uint256, MAX_COINS]: view
    def lp_price() -> uint256: view  # Exists only for cryptopools

interface PriceOracle:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable


MAX_COINS: constant(uint256) = 8

POOL: public(immutable(Pool))
COIN0_ORACLE: public(immutable(PriceOracle))
IS_CRYPTO: public(immutable(bool))
NO_ARGUMENT: public(immutable(bool))
N_COINS: public(immutable(uint256))
PRECISIONS: public(immutable(DynArray[uint256, MAX_COINS]))


@deploy
def __init__(pool: Pool, coin0_oracle: PriceOracle):
    is_crypto: bool = False
    no_argument: bool = False
    precisions: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])

    # Init variables for raw calls
    res: Bytes[1024] = empty(Bytes[1024])
    success: bool = False

    success, res = raw_call(pool.address, method_id("lp_price()"), max_outsize=32, is_static_call=True, revert_on_failure=False)
    if success and len(res) > 0:
        is_crypto = True

    # Find N_COINS and store PRECISIONS
    for i: uint256 in range(MAX_COINS + 1):
        success, res = raw_call(
            pool.address,
            abi_encode(i, method_id=method_id("coins(uint256)")),
            max_outsize=32, is_static_call=True, revert_on_failure=False)
        if not success:
            assert i != 0, "No coins(0)"
            N_COINS = i
            break

        coin: IERC20Detailed = IERC20Detailed(abi_decode(res, address))
        if coin.address != 0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE:
            precisions.append(10**(18 - convert(staticcall coin.decimals(), uint256)))
        else:
            precisions.append(1)

    # Check and record if pool requires coin id in argument or no
    if N_COINS == 2:
        success, res = raw_call(
            pool.address,
            abi_encode(empty(uint256), method_id=method_id("price_oracle(uint256)")),
            max_outsize=32, is_static_call=True, revert_on_failure=False)
        if not success:
            no_argument = True

    POOL = pool
    COIN0_ORACLE = coin0_oracle
    IS_CRYPTO = is_crypto
    NO_ARGUMENT = no_argument
    PRECISIONS = precisions


@internal
@view
def _coin0_oracle_price() -> uint256:
    if COIN0_ORACLE.address != empty(address):
        return staticcall COIN0_ORACLE.price()
    else:
        return 10**18


@internal
def _coin0_oracle_price_w() -> uint256:
    if COIN0_ORACLE.address != empty(address):
        return extcall COIN0_ORACLE.price_w()
    else:
        return 10**18


@internal
@view
def _price_in_coin0() -> uint256:
    if IS_CRYPTO:
        return staticcall POOL.lp_price()

    min_p: uint256 = max_value(uint256)
    for i: uint256 in range(N_COINS, bound=MAX_COINS):
        p_oracle: uint256 = 10 ** 18
        if i > 0:
            if NO_ARGUMENT:
                p_oracle = staticcall POOL.price_oracle()
            else:
                p_oracle = staticcall POOL.price_oracle(unsafe_sub(i, 1))

        if p_oracle < min_p:
            min_p = p_oracle

    return min_p


@external
@view
def price() -> uint256:
    return self._price_in_coin0() * self._coin0_oracle_price() // 10 ** 18


@external
def price_w() -> uint256:
    return self._price_in_coin0() * self._coin0_oracle_price_w() // 10 ** 18
