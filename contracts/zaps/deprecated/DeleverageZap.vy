# @version 0.3.10

"""
@title crvUSD de-leverage zap
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2023 - all rights reserved
"""

interface ERC20:
    def balanceOf(_for: address) -> uint256: view
    def approve(_spender: address, _value: uint256) -> bool: nonpayable
    def decimals() -> uint256: view

interface Router:
    def exchange(_route: address[11], _swap_params: uint256[5][5], _amount: uint256, _expected: uint256, _pools: address[5]) -> uint256: payable
    def get_dy(_route: address[11], _swap_params: uint256[5][5], _amount: uint256, _pools: address[5]) -> uint256: view

interface Controller:
    def calculate_debt_n1(collateral: uint256, debt: uint256, N: uint256) -> int256: view
    def user_state(user: address) -> uint256[4]: view


CRVUSD: constant(address) = 0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E

CONTROLLER: public(immutable(address))
COLLATERAL: public(immutable(address))
ROUTER: public(immutable(address))

routes: public(HashMap[uint256, address[11]])
route_params: public(HashMap[uint256, uint256[5][5]])
route_pools: public(HashMap[uint256, address[5]])
route_names: public(HashMap[uint256, String[100]])
routes_count: public(constant(uint256)) = 5


@external
def __init__(
        _controller: address,
        _collateral: address,
        _router: address,
        _routes: DynArray[address[11], 5],
        _route_params: DynArray[uint256[5][5], 5],
        _route_pools: DynArray[address[5], 5],
        _route_names: DynArray[String[100], 5],
):
    CONTROLLER = _controller
    COLLATERAL = _collateral
    ROUTER = _router

    for i in range(5):
        self.routes[i] = _routes[i]
        self.route_params[i] = _route_params[i]
        self.route_pools[i] = _route_pools[i]
        self.route_names[i] = _route_names[i]

    ERC20(_collateral).approve(_router, max_value(uint256), default_return_value=True)
    ERC20(_collateral).approve(_controller, max_value(uint256), default_return_value=True)
    ERC20(CRVUSD).approve(_controller, max_value(uint256), default_return_value=True)


@view
@external
def get_stablecoins(collateral: uint256, route_idx: uint256) -> uint256:
    return Router(ROUTER).get_dy(self.routes[route_idx], self.route_params[route_idx], collateral, self.route_pools[route_idx])


@external
@view
def calculate_debt_n1(collateral: uint256, route_idx: uint256, user: address) -> int256:
    """
    @notice Calculate the upper band number after deleverage repay, which means that
            collateral from user's position is converted to stablecoins to repay the debt.
    @param collateral Amount of collateral (at its native precision).
    @param route_idx Index of the route which should be use for exchange stablecoin to collateral.
    @return Upper band n1 (n1 <= n2) to deposit into. Signed integer.
    """
    deleverage_collateral: uint256 = Router(ROUTER).get_dy(self.routes[route_idx], self.route_params[route_idx], collateral, self.route_pools[route_idx])
    state: uint256[4] = Controller(CONTROLLER).user_state(user)  #collateral, stablecoin, debt, N
    assert state[1] == 0, "Underwater, only full repayment is allowed"
    assert deleverage_collateral < state[2], "Full repayment, position will be closed"

    return Controller(CONTROLLER).calculate_debt_n1(state[0] - collateral, state[2] - deleverage_collateral, state[3])


@external
@nonreentrant('lock')
def callback_repay(user: address, stablecoins: uint256, collateral: uint256, debt: uint256, callback_args: DynArray[uint256, 5]) -> uint256[2]:
    """
    @notice Callback method which should be called by controller to repay by selling collateral
    @param user Address of the user
    @param stablecoins Amount of user's stablecoin in AMM
    @param collateral Amount of user's collateral in AMM
    @param debt Current debt amount
    @param callback_args [route_idx, collateral_amount, min_recv]
    return [deleverage_stablecoins, (collateral - collateral_amount)], deleverage_stablecoins is
    the amount of stablecoins got as a result of selling collateral
    """
    assert msg.sender == CONTROLLER

    route_idx: uint256 = callback_args[0]
    collateral_amount: uint256 = callback_args[1]
    min_recv: uint256 = callback_args[2]
    deleverage_stablecoins: uint256 = Router(ROUTER).exchange(self.routes[route_idx], self.route_params[route_idx], collateral_amount, min_recv, self.route_pools[route_idx])

    return [deleverage_stablecoins, ERC20(COLLATERAL).balanceOf(self)]
