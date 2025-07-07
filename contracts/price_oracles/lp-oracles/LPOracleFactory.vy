# @version 0.4.1
#pragma optimize gas
#pragma evm-version shanghai


from snekmate.auth import ownable
initializes: ownable
exports: ownable.__interface__


interface IProxyOracleFactory:
    def deploy_proxy_oracle(_oracle: address) -> address: nonpayable


event DeployOracle:
    oracle: indexed(address)
    pool: indexed(address)
    coin0_oracle: address

event SetImplementations:
    stable_implementation: address
    crypto_implementation: address


struct OracleInfo:
    pool: address
    coin0_oracle: address


MAX_ORACLES: constant(uint256) = 50000
n_oracles: public(uint256)
oracles: public(address[MAX_ORACLES])

oracle_map: HashMap[address, HashMap[address, address]]  # oracle_map[pool][coin0_oracle] -> oracle
oracle_info: HashMap[address, OracleInfo]  # oracle_info[oracle] -> OracleInfo

STABLE_IMPLEMENTATION: public(immutable(address))
CRYPTO_IMPLEMENTATION: public(immutable(address))
PROXY_ORACLE_FACTORY: public(immutable(IProxyOracleFactory))


@deploy
def __init__(admin: address, _stable_implementation: address, _crypto_implementation: address, _proxy_oracle_factory: IProxyOracleFactory):
    """
    @notice Factory which creates StablePool and CryptoPool LP Oracles from blueprints
    @param admin Admin of the factory (ideally DAO)
    """
    ownable.__init__()
    ownable._transfer_ownership(admin)

    assert _stable_implementation != empty(address)
    assert _crypto_implementation != empty(address)
    assert _proxy_oracle_factory.address != empty(address)
    STABLE_IMPLEMENTATION = _stable_implementation
    CRYPTO_IMPLEMENTATION = _crypto_implementation
    PROXY_ORACLE_FACTORY = _proxy_oracle_factory


@external
@nonreentrant
def deploy_oracle(pool: address, coin0_oracle: address, use_proxy: bool = True, save_to_storage: bool = True) -> address:
    """
    @notice Deploy a new LP oracle
    @param pool Curve pool either stable or crypto
    @param coin0_oracle Oracle for the first coin of the pool
    @return Deployed oracle address
    """
    implementation: address = STABLE_IMPLEMENTATION
    if self._is_crypto(pool):
        implementation = CRYPTO_IMPLEMENTATION

    assert self.oracle_map[pool][coin0_oracle] == empty(address), "Oracle already exists"

    oracle: address = create_from_blueprint(implementation, pool, coin0_oracle, code_offset=3)
    if use_proxy:
        oracle = extcall PROXY_ORACLE_FACTORY.deploy_proxy_oracle(oracle)

    if save_to_storage:
        N: uint256 = self.n_oracles
        self.oracles[N] = oracle
        self.n_oracles = N + 1
        self.oracle_map[pool][coin0_oracle] = oracle
        self.oracle_info[oracle] = OracleInfo(pool=pool, coin0_oracle=coin0_oracle)

    log DeployOracle(oracle=oracle, pool=pool, coin0_oracle=coin0_oracle)

    return oracle


@external
@view
def get_oracle(pool: address, coin0_oracle: address) -> address:
    return self.oracle_map[pool][coin0_oracle]


@external
@view
def get_oracle_info(oracle: address) -> OracleInfo:
    return self.oracle_info[oracle]


@internal
@view
def _is_crypto(pool: address) -> bool:
    success: bool = False
    res: Bytes[32] = empty(Bytes[32])
    success, res = raw_call(pool, method_id("lp_price()"), max_outsize=32, is_static_call=True, revert_on_failure=False)
    if success and len(res) > 0:
        return True

    return False
