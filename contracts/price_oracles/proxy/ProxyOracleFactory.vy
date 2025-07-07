# @version 0.4.1
#pragma optimize gas
#pragma evm-version shanghai

"""
@title ProxyOracleFactory
@author Curve
@license GNU Affero General Public License v3.0 only
@notice Proxy oracle factory deploying proxy oracles and replacing price oracle contracts after the deployment
"""


from snekmate.auth import ownable
initializes: ownable
exports: ownable.__interface__


interface IProxyOracle:
    def initialize(_oracle: address, _max_deviation: uint256): nonpayable
    def set_price_oracle(_new_oracle: address, _skip_price_deviation_check: bool): nonpayable


event SetOracle:
    proxy: indexed(address)
    oracle: indexed(address)


PROXY_ORACLE_IMPLEMENTATION: public(immutable(address))
get_proxy: public(HashMap[address, address])  # get_proxy[oracle] -> proxy


@deploy
def __init__(admin: address, _proxy_oracle_implementation: address):
    """
    @notice Factory which creates StablePool and CryptoPool LP Oracles from blueprints
    @param admin Admin of the factory (ideally DAO)
    """
    ownable.__init__()
    ownable._transfer_ownership(admin)
    assert _proxy_oracle_implementation != empty(address)
    PROXY_ORACLE_IMPLEMENTATION = _proxy_oracle_implementation


@external
@nonreentrant
def deploy_proxy_oracle(_oracle: address) -> address:
    """
    @notice Deploy a new LP oracle
    @param _oracle Underlying Oracle
    @return Deployed oracle address
    """
    assert self.get_proxy[_oracle] == empty(address), "Oracle already exists"

    proxy: IProxyOracle = IProxyOracle(create_minimal_proxy_to(PROXY_ORACLE_IMPLEMENTATION))
    extcall proxy.initialize(_oracle, convert(100, uint256))
    self.get_proxy[_oracle] = proxy.address

    log SetOracle(proxy=proxy.address, oracle=_oracle)

    return proxy.address


@external
@nonreentrant
def set_new_oracle(_proxy: IProxyOracle, _new_oracle: address, _skip_price_deviation_check: bool = False):
    ownable._check_owner()
    extcall _proxy.set_price_oracle(_new_oracle, _skip_price_deviation_check)

    log SetOracle(proxy=_proxy.address, oracle=_new_oracle)
