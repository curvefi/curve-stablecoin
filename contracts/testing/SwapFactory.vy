# @version 0.3.9

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

interface ERC20:
    def balanceOf(_addr: address) -> uint256: view
    def decimals() -> uint256: view
    def totalSupply() -> uint256: view
    def approve(_spender: address, _amount: uint256): nonpayable


IMPL: immutable(address)
n: public(uint256)
pools: public(HashMap[uint256, address])
admin: public(address)


@external
def __init__(impl: address):
    IMPL = impl
    self.admin = msg.sender


@external
def deploy(coin_a: ERC20, coin_b: ERC20) -> address:
    pool: Swap = Swap(create_minimal_proxy_to(IMPL))
    pool.initialize(
        'TestName', 'TST',
        [coin_a.address, coin_b.address, empty(address), empty(address)],
        [10**(18-coin_a.decimals()) * 10**18, 10**(18-coin_b.decimals()) * 10**18, 0, 0],
        100,
        0)
    self.pools[self.n] = pool.address
    self.n += 1
    return pool.address
