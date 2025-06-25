# @version 0.4.1
#pragma optimize gas
#pragma evm-version shanghai


from snekmate.auth import ownable
initializes: ownable


event DeployOracle:
    oracle: indexed(address)
    pool: indexed(address)
    coin0_oracle: address
    implementation: address

event SetAdmin:
    admin: address

event SetImplementations:
    stable_implementation: address
    crypto_implementation: address


struct OracleInfo:
    pool: address
    coin0_oracle: address
    implementation: address


MAX_ORACLES: constant(uint256) = 50000
n_oracles: public(uint256)
oracles: public(address[MAX_ORACLES])

oracle_map: HashMap[address, HashMap[address, HashMap[address, address]]]  # oracle_map[pool][coin0_oracle][implementation] -> oracle
oracle_info: HashMap[address, OracleInfo]  # oracle_info[oracle] -> OracleInfo

stable_implementation: public(address)
crypto_implementation: public(address)


@deploy
def __init__(admin: address):
    """
    @notice Factory which creates StablePool and CryptoPool LP Oracles from blueprints
    @param admin Admin of the factory (ideally DAO)
    """
    ownable.__init__()
    ownable._transfer_ownership(admin)



@external
@nonreentrant
def deploy_oracle(pool: address, coin0_oracle: address) -> address:
    """
    @notice Deploy a new LP oracle
    @param pool Curve pool either stable or crypto
    @param coin0_oracle Oracle for the first coin of the pool
    @return Deployed oracle address
    """
    implementation: address = self.stable_implementation
    if self._is_crypto(pool):
        implementation = self.crypto_implementation

    assert implementation != empty(address), "Oracle implementation is not set"
    assert self.oracle_map[pool][coin0_oracle][implementation] == empty(address), "Oracle already exists"

    oracle: address = create_from_blueprint(implementation, pool, coin0_oracle, code_offset=3)

    N: uint256 = self.n_oracles
    self.oracles[N] = oracle
    self.n_oracles = N + 1
    self.oracle_map[pool][coin0_oracle][implementation] = oracle
    self.oracle_info[oracle] = OracleInfo(pool=pool, coin0_oracle=coin0_oracle, implementation=implementation)
    log DeployOracle(oracle=oracle, pool=pool, coin0_oracle=coin0_oracle, implementation=implementation)

    return oracle


@external
@view
def get_oracle(pool: address, coin0_oracle: address, implementation: address = empty(address)) -> address:
    _implementation: address = implementation
    if _implementation == empty(address):
        _implementation = self.stable_implementation
        if self._is_crypto(pool):
            _implementation = self.crypto_implementation

    return self.oracle_map[pool][coin0_oracle][_implementation]


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


@external
@nonreentrant
def set_implementations(stable_implementation: address, crypto_implementation: address):
    """
    @notice Set new implementations (blueprints) for stable and crypto oracles. Doesn't change existing ones
    @param stable_implementation Address of the StablePool LP Oracle blueprint
    @param crypto_implementation Address of the CryptoPool LP Oracle blueprint
    """
    ownable._check_owner()
    assert stable_implementation != empty(address)
    assert crypto_implementation != empty(address)
    self.stable_implementation = stable_implementation
    self.crypto_implementation = crypto_implementation
    log SetImplementations(stable_implementation=stable_implementation, crypto_implementation=crypto_implementation)
