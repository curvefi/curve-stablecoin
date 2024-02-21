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

ADMIN: public(immutable(address))
CONTROLLER_ADDRESS: immutable(address)
ROUTER: immutable(IROUTER)
SFRXETH: immutable(ISFRXETH)

routes: public(HashMap[uint256, address[9]])
route_params: public(HashMap[uint256, uint256[3][4]])
route_pools: public(HashMap[uint256, address[4]])
route_names: public(HashMap[uint256, String[64]])
routes_count: public(uint256)


@external
def __init__(
        _controller: address,
        _crvusd: address,
        _sfrxeth: address,
        _frxeth: address,
        _router: address,
        _routes: DynArray[address[9], 20],
        _route_params: DynArray[uint256[3][4], 20],
        _route_pools: DynArray[address[4], 20],
        _route_names: DynArray[String[64], 20],
):
    ADMIN = msg.sender
    CONTROLLER_ADDRESS = _controller
    ROUTER = IROUTER(_router)
    SFRXETH = ISFRXETH(_sfrxeth)

    for i in range(20):
        if i >= len(_routes):
            break
        self.routes[i] = _routes[i]
        self.route_params[i] = _route_params[i]
        self.route_pools[i] = _route_pools[i]
        self.route_names[i] = _route_names[i]
    self.routes_count = len(_routes)

    ERC20(_crvusd).approve(_controller, max_value(uint256), default_return_value=True)
    # SFRXETH.approve(_controller, max_value(uint256), default_return_value=True)
    ERC20(_frxeth).approve(_router, max_value(uint256), default_return_value=True)
    ERC20(_frxeth).approve(_sfrxeth, max_value(uint256), default_return_value=True)


@view
@external
@nonreentrant('lock')
def calc_output(collateral: uint256, route_idx: uint256) -> uint256:
    frxeth_amount: uint256 = SFRXETH.convertToAssets(collateral)
    crv_usd: uint256 = ROUTER.get_exchange_multiple_amount(self.routes[route_idx], self.route_params[route_idx], frxeth_amount, self.route_pools[route_idx])

    return crv_usd


@external
@nonreentrant('lock')
def callback_liquidate(user: address, stablecoins: uint256, collateral: uint256, debt: uint256, callback_args: DynArray[uint256, 5]) -> uint256[2]:
    assert msg.sender == CONTROLLER_ADDRESS

    route_idx: uint256 = callback_args[0]
    frxeth_amount: uint256 = SFRXETH.redeem(collateral, self, self)
    min_recv: uint256 = (debt - stablecoins) * 1005 / 1000 # 0.5% profit at least
    crv_usd: uint256 = ROUTER.exchange_multiple(self.routes[route_idx], self.route_params[route_idx], frxeth_amount, min_recv, self.route_pools[route_idx])

    return [crv_usd, 0]


@external
@nonreentrant('lock')
def add_routes(
        _routes: DynArray[address[9], 20],
        _route_params: DynArray[uint256[3][4], 20],
        _route_pools: DynArray[address[4], 20],
        _route_names: DynArray[String[64], 20],
):
    assert msg.sender == ADMIN, "admin only"

    routes_count: uint256 = self.routes_count
    for i in range(20):
        if i >= len(_routes):
            break
        idx: uint256 = routes_count + i
        self.routes[idx] = _routes[idx]
        self.route_params[idx] = _route_params[idx]
        self.route_pools[idx] = _route_pools[idx]
        self.route_names[idx] = _route_names[idx]
    self.routes_count += len(_routes)
