# @version 0.4.3
#pragma optimize gas
#pragma evm-version shanghai

"""
@title LPOracleFactory
@author Curve.Fi
@license GNU Affero General Public License v3.0 only
@notice Permissionless StablePool and CryptoPool LP Oracles deployer and registry
"""


from snekmate.auth import ownable
initializes: ownable
exports: ownable.__interface__


interface IProxyOracleFactory:
    def deploy_proxy_oracle(_oracle: address) -> address: nonpayable


event DeployOracle:
    oracle: indexed(address)
    pool: indexed(address)
    coin0_oracle: address


struct OracleInfo:
    pool: address
    coin0_oracle: address


oracle_map: HashMap[address, HashMap[address, address]]  # oracle_map[pool][coin0_oracle] -> oracle
oracle_info: public(HashMap[address, OracleInfo])  # oracle_info[oracle] -> OracleInfo

STABLE_IMPLEMENTATION: public(immutable(address))
CRYPTO_IMPLEMENTATION: public(immutable(address))
PROXY_ORACLE_FACTORY: public(immutable(IProxyOracleFactory))


@deploy
def __init__(_admin: address, _stable_implementation: address, _crypto_implementation: address, _proxy_oracle_factory: IProxyOracleFactory):
    """
    @notice Factory which creates StablePool and CryptoPool LP Oracles from blueprints
    @param admin Admin of the factory (ideally DAO)
    """
    ownable.__init__()
    ownable._transfer_ownership(_admin)

    assert _stable_implementation != empty(address)
    assert _crypto_implementation != empty(address)
    assert _proxy_oracle_factory.address != empty(address)
    STABLE_IMPLEMENTATION = _stable_implementation
    CRYPTO_IMPLEMENTATION = _crypto_implementation
    PROXY_ORACLE_FACTORY = _proxy_oracle_factory


@external
@nonreentrant
def deploy_oracle(_pool: address, _coin0_oracle: address, _use_proxy: bool = True) -> address[2]:
    """
    @notice Deploy a new LP oracle
    @param _pool Curve pool either stable or crypto
    @param _coin0_oracle Oracle for the first coin of the pool
    @param _use_proxy Whether to deploy proxy oracle or not
    @return [deployed oracle address, deployed proxy address or zero]
    """
    assert self.oracle_map[_pool][_coin0_oracle] == empty(address), "Oracle already exists"

    implementation: address = STABLE_IMPLEMENTATION
    if self._is_crypto(_pool):
        implementation = CRYPTO_IMPLEMENTATION
    oracle: address = create_from_blueprint(implementation, _pool, _coin0_oracle, code_offset=3)
    proxy: address = empty(address)
    if _use_proxy:
        proxy = extcall PROXY_ORACLE_FACTORY.deploy_proxy_oracle(oracle)
    self.oracle_map[_pool][_coin0_oracle] = oracle
    self.oracle_info[oracle] = OracleInfo(pool=_pool, coin0_oracle=_coin0_oracle)

    log DeployOracle(oracle=oracle, pool=_pool, coin0_oracle=_coin0_oracle)

    return [oracle, proxy]


@external
@view
def get_oracle(_pool: address, _coin0_oracle: address) -> address:
    """
    @param _pool Curve pool either stable or crypto
    @param _coin0_oracle Oracle for the first coin of the pool
    @return Oracle address
    """
    return self.oracle_map[_pool][_coin0_oracle]


@internal
@view
def _is_crypto(pool: address) -> bool:
    success: bool = False
    res: Bytes[32] = empty(Bytes[32])
    success, res = raw_call(pool, method_id("lp_price()"), max_outsize=32, is_static_call=True, revert_on_failure=False)
    if success and len(res) > 0:
        return True

    return False
