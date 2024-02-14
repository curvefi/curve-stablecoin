# @version 0.3.10
"""
@title Salvation
@license MIT
@author Curve.Fi
@notice Contract used to buy out coins from PegKeeper
"""

interface ERC20:
    def approve(_to: address, _value: uint256): nonpayable
    def transfer(_to: address, _value: uint256) -> bool: nonpayable
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable
    def balanceOf(_owner: address) -> uint256: view
    def decimals() -> uint256: view

interface CurvePool:
    def add_liquidity(_amounts: uint256[2], _min_mint_amount: uint256) -> uint256: nonpayable
    def remove_liquidity(_burn_amount: uint256, _min_amounts: uint256[N_COINS], _receiver: address = msg.sender) -> uint256[N_COINS]: nonpayable
    def remove_liquidity_imbalance(_amounts: uint256[2], _max_burn_amount: uint256, _receiver: address = msg.sender) -> uint256: nonpayable
    def remove_liquidity_one_coin(_burn_amount: uint256, i: int128, _min_received: uint256, _receiver: address = msg.sender) -> uint256: nonpayable
    def exchange(i: int128, j: int128, _dx: uint256, _min_dy: uint256, _receiver: address = msg.sender) -> uint256: nonpayable
    def coins(i: uint256) -> ERC20: view
    def balances(i_coin: uint256) -> uint256: view
    def price_oracle() -> uint256: view
    def get_p() -> uint256: view
    def balanceOf(arg0: address) -> uint256: view
    def totalSupply() -> uint256: view

interface PegKeeper:
    def update(_beneficiary: address = msg.sender) -> uint256: nonpayable
    def debt() -> uint256: view


N_COINS: constant(uint256) = 2
FEE_DENOMINATOR: constant(uint256) = 10 ** 10
EPS: constant(uint256) = 5 * 10 ** 14  # 0.05%


@internal
def _transfer_back(_coin: ERC20):
    assert _coin.transfer(msg.sender, _coin.balanceOf(self), default_return_value=True)  # safe transfer


@external
def buy_out(_pool: CurvePool, _pk: PegKeeper, _ransom: uint256, _max_total_supply: uint256, _max_price: uint256=10**18,
    _use_all: bool=False) -> uint256:
    """
    @notice Buy out coin with crvUSD from Peg Keeper
    @dev Need off-chain data for TotalSupply and Price
    @param _pool Pool which is used for Peg Keeper
    @param _pk Peg Keeper to buy out from
    @param _ransom Amount of crvUSD to use to buy out
    @param _max_total_supply Maximum totalSupply allowed for the pool to mitigate sandwich
    @param _max_price Max coin price in crvUSD to allow to buy out
    @param _use_all Use the whole ransom. Might be needed with small amount when fees affect peg
    @return Amount of debt bought out
    """
    max_price: uint256 = min(_max_price, _pool.price_oracle() * (10 ** 18 + EPS) / 10 ** 18)
    initial_price: uint256 = _pool.get_p()
    assert initial_price <= max_price
    assert _pool.totalSupply() <= _max_total_supply

    initial_debt: uint256 = _pk.debt()
    dec: uint256 = 10 ** (18 - _pool.coins(0).decimals())
    initial_amounts: uint256[2] = [_pool.balances(0) * dec, _pool.balances(1)]

    # Add crvUSD, so there is more crvUSD than TUSD and it is withdrawn
    amount: uint256 = _ransom
    if not _use_all:
        amount = min(amount, 5 * initial_debt + initial_amounts[0] - initial_amounts[1])
    crvUSD: ERC20 = _pool.coins(1)
    crvUSD.transferFrom(msg.sender, self, amount)
    crvUSD.approve(_pool.address, max_value(uint256))
    lp: uint256 = _pool.add_liquidity([0, amount], 0)

    # PegKeeper takes back crvUSD
    lp += _pk.update()

    # Withdraw crvUSD to stabilize
    withdraw_amount: uint256 = _pool.balances(1) - initial_amounts[1] * _pool.balances(0) * dec / initial_amounts[0]
    _pool.remove_liquidity_imbalance(
        [0, withdraw_amount],
        lp,
        msg.sender,
    )

    # Remove everything else
    _pool.remove_liquidity(_pool.balanceOf(self), [0, 0], msg.sender)

    assert convert(abs(convert(_pool.get_p(), int256) - convert(initial_price, int256)), uint256) * 10 ** 18 / initial_price < EPS

    # Just in case
    for coin in [_pool.coins(0), crvUSD, ERC20(_pool.address)]:
        self._transfer_back(coin)

    return initial_debt - _pk.debt()
