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
from snekmate.utils import math


interface Pool:
    def coins(i: uint256) -> address: view
    def balances(i: uint256) -> uint256: view
    def price_oracle(i: uint256 = 0) -> uint256: view  # Universal method!
    def stored_rates() -> DynArray[uint256, MAX_COINS]: view
    def totalSupply() -> uint256: view


interface PriceOracle:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable


MAX_COINS: constant(uint256) = 8
RATE_MAX_SPEED: constant(uint256) = 10**16 // 60  # Max speed of Rate change
BALANCES_MA_TIME: public(constant(uint256)) = 866  # 600s / ln(2)

POOL: public(immutable(Pool))
COIN0_ORACLE: public(immutable(PriceOracle))
NO_ARGUMENT: public(immutable(bool))
N_COINS: public(immutable(uint256))
USE_RATES: public(immutable(bool))
PRECISIONS: public(immutable(DynArray[uint256, MAX_COINS]))
RATES_ALL_ONES: public(immutable(DynArray[uint256, MAX_COINS]))

last_rates: public(DynArray[uint256, MAX_COINS])
last_balances: public(DynArray[uint256, MAX_COINS])
last_supply: public(uint256)
last_price: public(uint256)
last_timestamp: public(uint256)


@deploy
def __init__(pool: Pool, coin0_oracle: PriceOracle):
    use_rates: bool = False
    no_argument: bool = False
    precisions: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    stored_rates: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])

    # Init variable for raw calls
    success: bool = False

    # Find N_COINS and store PRECISIONS
    for i: uint256 in range(MAX_COINS + 1):
        res: Bytes[32] = empty(Bytes[32])
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
        res: Bytes[32] = empty(Bytes[32])
        success, res = raw_call(
            pool.address,
            abi_encode(empty(uint256), method_id=method_id("price_oracle(uint256)")),
            max_outsize=32, is_static_call=True, revert_on_failure=False)
        if not success:
            no_argument = True

    res: Bytes[1024] = empty(Bytes[1024])
    success, res = raw_call(pool.address, method_id("stored_rates()"), max_outsize=1024, is_static_call=True, revert_on_failure=False)
    if success and len(res) > 0:
        stored_rates = abi_decode(res, DynArray[uint256, MAX_COINS])
    else:
        for i: uint256 in range(MAX_COINS):
            if i == N_COINS:
                break
            stored_rates.append(10**18)

    for r: uint256 in stored_rates:
        if r != 10**18:
            use_rates = True
            break

    POOL = pool
    COIN0_ORACLE = coin0_oracle
    NO_ARGUMENT = no_argument
    PRECISIONS = precisions
    USE_RATES = use_rates
    RATES_ALL_ONES = stored_rates

    balances: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    for i: uint256 in range(MAX_COINS):
        if i == N_COINS:
            break
        balances.append(staticcall pool.balances(i))
    supply: uint256 = staticcall pool.totalSupply()

    self.last_rates = stored_rates
    self.last_balances = balances
    self.last_supply = supply
    self.last_price = self._price_in_coin0(balances, supply, stored_rates) * (extcall COIN0_ORACLE.price_w()) // 10**18
    self.last_timestamp = block.timestamp


@internal
@view
def _raw_stored_rates() -> DynArray[uint256, MAX_COINS]:
    if USE_RATES:
        return staticcall POOL.stored_rates()
    else:
        return RATES_ALL_ONES


@internal
@view
def _stored_rates() -> DynArray[uint256, MAX_COINS]:
    stored_rates: DynArray[uint256, MAX_COINS] = self._raw_stored_rates()
    if not USE_RATES:
        return stored_rates

    last_rates: DynArray[uint256, MAX_COINS] = self.last_rates

    rates: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    for i: uint256 in range(MAX_COINS):
        if i == N_COINS:
            break

        if len(last_rates) == 0 or last_rates[i] == stored_rates[i]:
            rates.append(stored_rates[i])
        elif stored_rates[i] > last_rates[i]:
            rates.append(
                min(
                    stored_rates[i],
                    last_rates[i] * (10**18 + RATE_MAX_SPEED * (block.timestamp - self.last_timestamp)) // 10**18
                )
            )
        else:
            rates.append(
                max(
                    stored_rates[i],
                    last_rates[i] * (10**18 - min(RATE_MAX_SPEED * (block.timestamp - self.last_timestamp), 10**18)) // 10**18
                )
            )

    return rates


@external
@view
def stored_rates() -> DynArray[uint256, MAX_COINS]:
    return self._stored_rates()


@internal
@view
def _ema_balances_and_supply() -> (DynArray[uint256, MAX_COINS], uint256):
    last_timestamp: uint256 = self.last_timestamp
    alpha: uint256 = 10**18
    if last_timestamp < block.timestamp:
        alpha = convert(math._wad_exp(- convert((block.timestamp - last_timestamp) * 10**18 // BALANCES_MA_TIME, int256)), uint256)

    balances: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    for i: uint256 in range(MAX_COINS):
        if i == N_COINS:
            break
        balance: uint256 = self.last_balances[i]
        if alpha != 10**18:
            # alpha = 1.0 when dt = 0
            # alpha = 0.0 when dt = inf
            new_balance: uint256 = staticcall POOL.balances(i)
            balance = (new_balance * (10**18 - alpha) + balance * alpha) // 10**18
        balances.append(balance)

    supply: uint256 = self.last_supply
    if alpha != 10 ** 18:
        # alpha = 1.0 when dt = 0
        # alpha = 0.0 when dt = inf
        new_supply: uint256 = staticcall POOL.totalSupply()
        supply = (new_supply * (10 ** 18 - alpha) + supply * alpha) // 10 ** 18

    return balances, supply


@internal
@view
def _price_in_coin0(balances: DynArray[uint256, MAX_COINS], supply: uint256, rates: DynArray[uint256, MAX_COINS]) -> uint256:
    numerator: uint256 = 0
    denominator: uint256 = supply
    for i: uint256 in range(MAX_COINS):
        if i == N_COINS:
            break

        p_oracle: uint256 = 10 ** 18
        if i > 0:
            if NO_ARGUMENT:
                p_oracle = staticcall POOL.price_oracle()
            else:
                p_oracle = staticcall POOL.price_oracle(unsafe_sub(i, 1))

        if i > 0:
            numerator += balances[i] * PRECISIONS[i] * rates[i] // rates[0] * p_oracle // 10**18
        else:
            numerator += balances[i] * PRECISIONS[i] * p_oracle // 10**18

    return numerator * 10**18 // denominator


@external
@view
def price() -> uint256:
    balances: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    supply: uint256 = 0
    balances, supply = self._ema_balances_and_supply()
    rates: DynArray[uint256, MAX_COINS] = self._stored_rates()
    return self._price_in_coin0(balances, supply, rates) * (staticcall COIN0_ORACLE.price()) // 10 ** 18


@external
def price_w() -> uint256:
    if self.last_timestamp == block.timestamp:
        return self.last_price
    else:
        balances: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
        supply: uint256 = 0
        balances, supply = self._ema_balances_and_supply()
        rates: DynArray[uint256, MAX_COINS] = self._stored_rates()
        p: uint256 = self._price_in_coin0(balances, supply, rates) * (extcall COIN0_ORACLE.price_w()) // 10**18

        if USE_RATES:
            self.last_rates = rates
        self.last_balances = balances
        self.last_supply = supply
        self.last_price = p
        self.last_timestamp = block.timestamp

        return p
