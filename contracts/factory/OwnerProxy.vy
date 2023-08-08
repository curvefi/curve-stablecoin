# @version 0.3.9
"""
@title Curve StableSwap Owner Proxy
@author Curve Finance
@license MIT
@notice Allows DAO ownership of `Factory` and it's deployed pools
"""

interface ManagerProxy:
    def gauge_manager(_gauge: address) -> address: view

interface Curve:
    def ramp_A(_future_A: uint256, _future_time: uint256): nonpayable
    def stop_ramp_A(): nonpayable
    def set_ma_exp_time(_ma_exp_time: uint256): nonpayable
    def ma_exp_time() -> uint256: view
    def commit_new_fee(_new_fee: uint256): nonpayable
    def apply_new_fee(): nonpayable

interface Gauge:
    def set_killed(_is_killed: bool): nonpayable
    def add_reward(_reward_token: address, _distributor: address): nonpayable
    def set_reward_distributor(_reward_token: address, _distributor: address): nonpayable

interface Factory:
    def add_base_pool(
        _base_pool: address,
        _fee_receiver: address,
        _asset_type: uint256,
        _implementations: address[10],
    ): nonpayable
    def set_metapool_implementations(
        _base_pool: address,
        _implementations: address[10],
    ): nonpayable
    def set_plain_implementations(
        _n_coins: uint256,
        _implementations: address[10],
    ): nonpayable
    def set_gauge_implementation(_gauge_implementation: address): nonpayable
    def set_fee_receiver(_base_pool: address, _fee_receiver: address): nonpayable
    def commit_transfer_ownership(addr: address): nonpayable
    def accept_transfer_ownership(): nonpayable
    def set_manager(_manager: address): nonpayable
    def deploy_plain_pool(
        _name: String[32],
        _symbol: String[10],
        _coins: address[4],
        _A: uint256,
        _fee: uint256,
        _asset_type: uint256,
        _implementation_idx: uint256,
    ) -> address: nonpayable
    def deploy_gauge(_pool: address) -> address: nonpayable
    def add_token_to_whitelist(coin: address, _add: bool): nonpayable


event CommitAdmins:
    ownership_admin: address
    parameter_admin: address
    emergency_admin: address

event ApplyAdmins:
    ownership_admin: address
    parameter_admin: address
    emergency_admin: address


FACTORY: public(immutable(address))
OLD_MANAGER_PROXY: public(immutable(address))


ownership_admin: public(address)
parameter_admin: public(address)
emergency_admin: public(address)

future_ownership_admin: public(address)
future_parameter_admin: public(address)
future_emergency_admin: public(address)

gauge_manager: public(HashMap[address, address])


@external
def __init__(
    _ownership_admin: address,
    _parameter_admin: address,
    _emergency_admin: address,
    _factory: address,
    _old_manager_proxy: address,
):
    FACTORY = _factory
    OLD_MANAGER_PROXY = _old_manager_proxy

    self.ownership_admin = _ownership_admin
    self.parameter_admin = _parameter_admin
    self.emergency_admin = _emergency_admin


@external
def deploy_plain_pool(
    _name: String[32],
    _symbol: String[10],
    _coins: address[4],
    _A: uint256,
    _fee: uint256,
    _asset_type: uint256 = 0,
    _implementation_idx: uint256 = 0,
    _ma_exp_time: uint256 = 600
) -> address:
    pool: address = Factory(FACTORY).deploy_plain_pool(
        _name,
        _symbol,
        _coins,
        _A,
        _fee,
        _asset_type,
        _implementation_idx,
    )
    if _ma_exp_time != 600:
        Curve(pool).set_ma_exp_time(_ma_exp_time)
    return pool


@external
def deploy_gauge(_pool: address, _manager: address = msg.sender) -> address:
    """
    @notice Deploy a gauge, and set _manager as the manager
    @param _pool The pool to deploy a gauge for
    @param _manager The account to which will manage rewards for the gauge
    """
    gauge: address = Factory(FACTORY).deploy_gauge(_pool)

    self.gauge_manager[gauge] = _manager
    return gauge


@external
def commit_set_admins(_o_admin: address, _p_admin: address, _e_admin: address):
    """
    @notice Set ownership admin to `_o_admin`, parameter admin to `_p_admin` and emergency admin to `_e_admin`
    @param _o_admin Ownership admin
    @param _p_admin Parameter admin
    @param _e_admin Emergency admin
    """
    assert msg.sender == self.ownership_admin, "Access denied"

    self.future_ownership_admin = _o_admin
    self.future_parameter_admin = _p_admin
    self.future_emergency_admin = _e_admin

    log CommitAdmins(_o_admin, _p_admin, _e_admin)


@external
def apply_set_admins():
    """
    @notice Apply the effects of `commit_set_admins`
    """
    assert msg.sender == self.ownership_admin, "Access denied"

    _o_admin: address = self.future_ownership_admin
    _p_admin: address = self.future_parameter_admin
    _e_admin: address = self.future_emergency_admin
    self.ownership_admin = _o_admin
    self.parameter_admin = _p_admin
    self.emergency_admin = _e_admin

    log ApplyAdmins(_o_admin, _p_admin, _e_admin)


@external
def set_ma_exp_time(_pool: address, _ma_exp_time: uint256):
    assert msg.sender == self.parameter_admin, "Access denied"
    Curve(_pool).set_ma_exp_time(_ma_exp_time)


@external
def commit_new_fee(_pool: address, _new_fee: uint256):
    assert msg.sender == self.parameter_admin, "Access denied"

    Curve(_pool).commit_new_fee(_new_fee)


@external
def apply_new_fee(_pool: address):
    Curve(_pool).apply_new_fee()


@external
@nonreentrant('lock')
def ramp_A(_pool: address, _future_A: uint256, _future_time: uint256):
    """
    @notice Start gradually increasing A of `_pool` reaching `_future_A` at `_future_time` time
    @param _pool Pool address
    @param _future_A Future A
    @param _future_time Future time
    """
    assert msg.sender == self.parameter_admin, "Access denied"
    Curve(_pool).ramp_A(_future_A, _future_time)


@external
@nonreentrant('lock')
def stop_ramp_A(_pool: address):
    """
    @notice Stop gradually increasing A of `_pool`
    @param _pool Pool address
    """
    assert msg.sender in [self.parameter_admin, self.emergency_admin], "Access denied"
    Curve(_pool).stop_ramp_A()


@external
@nonreentrant('lock')
def add_token_to_whitelist(_target: address, coin: address, _add: bool):
    """
    @notice adds a token to a list of tokens with which plain pools are allowed
    @param coin Address of the coin to add
    """
    assert msg.sender == self.ownership_admin, "Access denied"
    Factory(_target).add_token_to_whitelist(coin, _add)


@external
def add_base_pool(
    _target: address,
    _base_pool: address,
    _fee_receiver: address,
    _asset_type: uint256,
    _implementations: address[10],
):
    assert msg.sender == self.ownership_admin, "Access denied"

    Factory(_target).add_base_pool(_base_pool, _fee_receiver, _asset_type, _implementations)


@external
def set_metapool_implementations(
    _target: address,
    _base_pool: address,
    _implementations: address[10],
):
    """
    @notice Set implementation contracts for a metapool
    @dev Only callable by admin
    @param _base_pool Pool address to add
    @param _implementations Implementation address to use when deploying metapools
    """
    assert msg.sender == self.ownership_admin, "Access denied"
    Factory(_target).set_metapool_implementations(_base_pool, _implementations)


@external
def set_plain_implementations(
    _target: address,
    _n_coins: uint256,
    _implementations: address[10],
):
    assert msg.sender == self.ownership_admin, "Access denied"
    Factory(_target).set_plain_implementations(_n_coins, _implementations)


@external
def set_gauge_implementation(_target: address, _gauge_implementation: address):
    assert msg.sender == self.ownership_admin, "Access denied"
    Factory(_target).set_gauge_implementation(_gauge_implementation)


@external
def set_fee_receiver(_target: address, _base_pool: address, _fee_receiver: address):
    assert msg.sender == self.ownership_admin, "Access denied"
    Factory(_target).set_fee_receiver(_base_pool, _fee_receiver)


@external
def set_factory_manager(_target: address, _manager: address):
    assert msg.sender in [self.ownership_admin, self.emergency_admin], "Access denied"
    Factory(_target).set_manager(_manager)


@external
def set_gauge_manager(_gauge: address, _manager: address):
    """
    @notice Set the manager
    @dev Callable by the admin or existing manager
    @param _manager Manager address
    """
    assert msg.sender in [self.ownership_admin, self.emergency_admin, self.gauge_manager[_gauge]], "Access denied"

    self.gauge_manager[_gauge] = _manager


@external
def commit_transfer_ownership(_target: address, _new_admin: address):
    """
    @notice Transfer ownership of `_target` to `_new_admin`
    @param _target `Factory` deployment address
    @param _new_admin New admin address
    """
    assert msg.sender == self.ownership_admin  # dev: admin only

    Factory(_target).commit_transfer_ownership(_new_admin)


@external
def accept_transfer_ownership(_target: address):
    """
    @notice Accept a pending ownership transfer
    @param _target `Factory` deployment address
    """
    Factory(_target).accept_transfer_ownership()


@external
def set_killed(_gauge: address, _is_killed: bool):
    assert msg.sender in [self.ownership_admin, self.emergency_admin]
    Gauge(_gauge).set_killed(_is_killed)


@external
def add_reward(_gauge: address, _reward_token: address, _distributor: address):
    assert msg.sender in [self.ownership_admin, self.gauge_manager[_gauge]]
    Gauge(_gauge).add_reward(_reward_token, _distributor)


@external
def set_reward_distributor(_gauge: address, _reward_token: address, _distributor: address):
    assert msg.sender in [self.ownership_admin, self.gauge_manager[_gauge]]
    Gauge(_gauge).set_reward_distributor(_reward_token, _distributor)


@external
def migrate_gauge_manager(_gauge: address):
    manager: address = ManagerProxy(OLD_MANAGER_PROXY).gauge_manager(_gauge)
    if manager != empty(address) and self.gauge_manager[_gauge] == empty(address):
        self.gauge_manager[_gauge] = manager
