# @version 0.3.7

interface ERC20:
    def transfer(_to: address, _value: uint256) -> bool: nonpayable
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable
    def approve(_spender: address, _value: uint256) -> bool: nonpayable
    def balanceOf(_for: address) -> uint256: view

interface CRYPTOPOOL:
    def exchange(i: uint256, j: uint256, dx: uint256, min_dy: uint256,
                 use_eth: bool = False, receiver: address = msg.sender) -> uint256: payable
    def get_dy(i: uint256, j: uint256, dx: uint256) -> uint256: view

interface LLAMMA:
    def exchange(i: uint256, j: uint256, in_amount: uint256, min_amount: uint256, _for: address = msg.sender) -> uint256[2]: nonpayable
    def get_dy(i: uint256, j: uint256, in_amount: uint256) -> uint256: view
    def get_dxdy(i: uint256, j: uint256, in_amount: uint256) -> uint256[2]: view


LLAMMA_ADDRESS: immutable(address)
CRYPTOPOOL_ADDRESS: immutable(address)
CRVUSD_ADDRESS: immutable(address)
COLLATERAL_ADDRESS: immutable(address)


@external
def __init__(_llamma: address, _cryptopool: address, _crvusd: address, _collateral: address):
    LLAMMA_ADDRESS = _llamma
    CRYPTOPOOL_ADDRESS = _cryptopool
    CRVUSD_ADDRESS = _crvusd
    COLLATERAL_ADDRESS = _collateral

    ERC20(_crvusd).approve(_llamma, max_value(uint256), default_return_value=True)
    ERC20(_crvusd).approve(_cryptopool, max_value(uint256), default_return_value=True)
    ERC20(_collateral).approve(_llamma, max_value(uint256), default_return_value=True)
    ERC20(_collateral).approve(_cryptopool, max_value(uint256), default_return_value=True)


@view
@external
@nonreentrant('lock')
def calc_output(in_amount: uint256, liquidation: bool) -> uint256[3]:
    """
    @notice Calculate liquidator profit
    @param in_amount Amount of collateral going in
    @param liquidation Liquidation or de-liquidation
    @return (amount of collateral going out, amount of crvUSD in the middle, amount of crvUSD DONE)
    """
    output: uint256 = 0
    crv_usd: uint256 = 0
    done: uint256 = 0
    if liquidation:
        # collateral --> CRYPTOPOOL --> crvUSD --> LLAMMA --> collateral
        crv_usd = CRYPTOPOOL(CRYPTOPOOL_ADDRESS).get_dy(1, 0, in_amount)
        dxdy: uint256[2] = LLAMMA(LLAMMA_ADDRESS).get_dxdy(0, 1, crv_usd)
        done = dxdy[0]  # crvUSD
        output = dxdy[1]
    else:
        # de-liquidation
        # collateral --> LLAMMA --> crvUSD --> CRYPTOPOOL --> collateral
        dxdy: uint256[2] = LLAMMA(LLAMMA_ADDRESS).get_dxdy(1, 0, in_amount)
        done = dxdy[0]  # collateral
        crv_usd = dxdy[1]
        output = CRYPTOPOOL(CRYPTOPOOL_ADDRESS).get_dy(0, 1, crv_usd)

    return [output, crv_usd, done]


@external
@nonreentrant('lock')
def exchange(in_amount: uint256, min_crv_usd: uint256, min_output: uint256, liquidation: bool,  _for: address = msg.sender) -> uint256[2]:
    assert ERC20(COLLATERAL_ADDRESS).transferFrom(msg.sender, self, in_amount, default_return_value=True)

    output: uint256 = 0
    crv_usd: uint256 = 0
    if liquidation:
        # collateral --> CRYPTOPOOL --> crvUSD --> LLAMMA --> collateral
        crv_usd = CRYPTOPOOL(CRYPTOPOOL_ADDRESS).exchange(1, 0, in_amount, min_crv_usd, False)
        out_in: uint256[2] = LLAMMA(LLAMMA_ADDRESS).exchange(0, 1, crv_usd, min_output)
        output = out_in[1]
    else:
        # de-liquidation
        # collateral --> LLAMMA --> crvUSD --> CRYPTOPOOL --> collateral
        out_in: uint256[2] = LLAMMA(LLAMMA_ADDRESS).exchange(1, 0, in_amount, min_crv_usd)
        crv_usd = out_in[1]
        output = CRYPTOPOOL(CRYPTOPOOL_ADDRESS).exchange(0, 1, crv_usd, min_output, False)

    collateral_balance: uint256 = ERC20(COLLATERAL_ADDRESS).balanceOf(self)
    ERC20(COLLATERAL_ADDRESS).transfer(_for, collateral_balance)
    crv_usd_balance: uint256 = ERC20(CRVUSD_ADDRESS).balanceOf(self)
    ERC20(CRVUSD_ADDRESS).transfer(_for, crv_usd_balance)

    return [output, crv_usd]
