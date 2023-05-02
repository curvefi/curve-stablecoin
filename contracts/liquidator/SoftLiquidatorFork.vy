# @version 0.3.7

interface ERC20:
    def transfer(_to: address, _value: uint256) -> bool: nonpayable
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable
    def approve(_spender: address, _value: uint256) -> bool: nonpayable
    def balanceOf(_for: address) -> uint256: view

interface ILLAMMA:
    def exchange(i: uint256, j: uint256, in_amount: uint256, min_amount: uint256, _for: address = msg.sender) -> uint256[2]: nonpayable
    def get_dy(i: uint256, j: uint256, in_amount: uint256) -> uint256: view
    def get_dxdy(i: uint256, j: uint256, in_amount: uint256) -> uint256[2]: view

interface IROUTER:
    def exchange_multiple(_route: address[9], _swap_params: uint256[3][4], _amount: uint256, _expected: uint256, _pools: address[4]) -> uint256: payable
    def get_exchange_multiple_amount(_route: address[9], _swap_params: uint256[3][4], _amount: uint256, _pools: address[4]) -> uint256: view

interface ISFRXETH:
    def transfer(_to: address, _value: uint256) -> bool: nonpayable
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable
    def approve(_spender: address, _value: uint256) -> bool: nonpayable
    def balanceOf(_for: address) -> uint256: view
    def convertToShares(assets: uint256) -> uint256: view
    def convertToAssets(shares: uint256) -> uint256: view
    def deposit(assets: uint256, receiver: address) -> uint256: nonpayable
    def redeem(shares: uint256, receiver: address, owner: address) -> uint256: nonpayable


LLAMMA: immutable(ILLAMMA)
ROUTER: immutable(IROUTER)
CRVUSD: immutable(ERC20)
SFRXETH: immutable(ISFRXETH)
FRXETH: immutable(ERC20)


@external
def __init__(_llamma: address, _router: address, _crvusd: address, _sfrxeth: address, _frxeth: address):
    LLAMMA = ILLAMMA(_llamma)
    ROUTER = IROUTER(_router)
    CRVUSD = ERC20(_crvusd)
    SFRXETH = ISFRXETH(_sfrxeth)
    FRXETH = ERC20(_frxeth)

    CRVUSD.approve(_llamma, max_value(uint256), default_return_value=True)
    CRVUSD.approve(_router, max_value(uint256), default_return_value=True)
    SFRXETH.approve(_llamma, max_value(uint256), default_return_value=True)
    FRXETH.approve(_router, max_value(uint256), default_return_value=True)
    FRXETH.approve(_sfrxeth, max_value(uint256), default_return_value=True)


@view
@external
def convert_to_assets(shares: uint256) -> uint256:
    return SFRXETH.convertToAssets(shares)


@view
@external
@nonreentrant('lock')
def calc_output(in_amount: uint256, liquidation: bool, _route: address[9], _swap_params: uint256[3][4], _pools: address[4]) -> uint256[3]:
    """
    @notice Calculate liquidator profit
    @param in_amount Amount of collateral going in
    @param liquidation Liquidation or de-liquidation
    @param _route Arg for router
    @param _swap_params Arg for router
    @param _pools Arg for router
    @return (amount of collateral going out, amount of crvUSD in the middle, amount of crvUSD/collateral DONE)
    """
    output: uint256 = 0
    crv_usd: uint256 = 0
    done: uint256 = 0
    if liquidation:
        # collateral --> CRYPTOPOOL --> crvUSD --> LLAMMA --> collateral
        frxeth_amount: uint256 = SFRXETH.convertToAssets(in_amount)
        crv_usd = ROUTER.get_exchange_multiple_amount(_route, _swap_params, frxeth_amount, _pools)
        dxdy: uint256[2] = LLAMMA.get_dxdy(0, 1, crv_usd)
        done = dxdy[0]  # crvUSD
        output = dxdy[1]
    else:
        # de-liquidation
        # collateral --> LLAMMA --> crvUSD --> CRYPTOPOOL --> collateral
        dxdy: uint256[2] = LLAMMA.get_dxdy(1, 0, in_amount)
        done = dxdy[0]  # collateral
        crv_usd = dxdy[1]
        output = ROUTER.get_exchange_multiple_amount(_route, _swap_params, crv_usd, _pools)
        output = SFRXETH.convertToShares(output)

    return [output, crv_usd, done]


@external
@nonreentrant('lock')
def exchange(
        in_amount: uint256,
        min_crv_usd: uint256,
        min_output: uint256,
        liquidation: bool,
        _route: address[9],
        _swap_params: uint256[3][4],
        _pools: address[4],
        _for: address = msg.sender,
) -> uint256[2]:
    assert SFRXETH.transferFrom(msg.sender, self, in_amount, default_return_value=True)

    output: uint256 = 0
    crv_usd: uint256 = 0
    if liquidation:
        # collateral --> CRYPTOPOOL --> crvUSD --> LLAMMA --> collateral
        frxeth_amount: uint256 = SFRXETH.redeem(in_amount, self, self)
        crv_usd = ROUTER.exchange_multiple(_route, _swap_params, frxeth_amount, min_crv_usd, _pools)
        out_in: uint256[2] = LLAMMA.exchange(0, 1, crv_usd, min_output)
        output = out_in[1]
    else:
        # de-liquidation
        # collateral --> LLAMMA --> crvUSD --> CRYPTOPOOL --> collateral
        out_in: uint256[2] = LLAMMA.exchange(1, 0, in_amount, min_crv_usd)
        crv_usd = out_in[1]
        output = ROUTER.exchange_multiple(_route, _swap_params, crv_usd, min_output, _pools)
        output = SFRXETH.deposit(output, self)

    collateral_balance: uint256 = SFRXETH.balanceOf(self)
    SFRXETH.transfer(_for, collateral_balance)
    crv_usd_balance: uint256 = CRVUSD.balanceOf(self)
    CRVUSD.transfer(_for, crv_usd_balance)

    return [output, crv_usd]
