# pragma version 0.4.3

MAX_COINS: constant(uint256) = 4

interface Swap:
    def initialize(
        _name: String[32],
        _symbol: String[10],
        _coins: address[4],
        _rate_multipliers: uint256[4],
        _A: uint256,
        _fee: uint256,
    ): nonpayable
    def factory() -> address: view

interface FactoryNG:
    def deploy_plain_pool(
        _name: String[32],
        _symbol: String[10],
        _coins: DynArray[address, MAX_COINS],
        _A: uint256,
        _fee: uint256,
        _offpeg_fee_multiplier: uint256,
        _ma_exp_time: uint256,
        _implementation_idx: uint256,
        _asset_types: DynArray[uint8, MAX_COINS],
        _method_ids: DynArray[Bytes[4], MAX_COINS],
        _oracles: DynArray[address, MAX_COINS],
    ) -> address: nonpayable

interface ERC20:
    def balanceOf(_addr: address) -> uint256: view
    def decimals() -> uint256: view
    def totalSupply() -> uint256: view
    def approve(_spender: address, _amount: uint256): nonpayable


IMPL: immutable(address)
n: public(uint256)
pools: public(HashMap[uint256, address])
admin: public(address)

factory_ng: FactoryNG
rate_oracle: address

@external
def __init__(impl: address):
    IMPL = impl
    self.admin = msg.sender


@external
def deploy(coin_a: ERC20, coin_b: ERC20) -> address:
    pool: Swap = Swap(create_minimal_proxy_to(IMPL))
    pool.initialize(
        "TestName",
        "TST",
        [address(coin_a), address(coin_b), empty(address), empty(address)],
        [10**(18 - coin_a.decimals()) * 10**18, 10**(18 - coin_b.decimals()) * 10**18, 0, 0],
        100,
        0,
    )
    self.pools[self.n] = address(pool)
    self.n += 1
    return address(pool)


@external
def deploy_ng(coin_a: ERC20, coin_b: ERC20) -> address:
    assert address(self.factory_ng) != empty(address), "Factory not set"
    pool: address = self.factory_ng.deploy_plain_pool(
        "TestName-ng",
        "TST-ng",
        [address(coin_a), address(coin_b)],
        100,
        0,
        10000000000,
        866,
        0,
        [1, 1],
        [method_id("get00()"), method_id("get11()")],
        [self.rate_oracle, self.rate_oracle],
    )
    self.pools[self.n] = pool
    self.n += 1
    return pool
