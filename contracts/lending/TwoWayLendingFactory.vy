# @version 0.3.10
"""
@title TwoWayLendingFactory
@notice Factory of rehypothecated lending vaults: collateral can be lent out.
@author Curve.fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
"""

interface Vault:
    def initialize(
        amm_impl: address,
        controller_impl: address,
        borrowed_token: address,
        collateral_token: address,
        A: uint256,
        fee: uint256,
        price_oracle: address,
        monetary_policy: address,
        loan_discount: uint256,
        liquidation_discount: uint256
    ) -> (address, address): nonpayable
    def pricePerShare() -> uint256: view
    def amm() -> address: view
    def controller() -> address: view
    def borrowed_token() -> address: view
    def collateral_token() -> address: view
    def price_oracle() -> address: view

interface Controller:
    def monetary_policy() -> address: view

interface Pool:
    def price_oracle(i: uint256 = 0) -> uint256: view  # Universal method!
    def coins(i: uint256) -> address: view


event SetImplementations:
    amm: address
    controller: address
    vault: address
    pool_price_oracle: address
    wrapper_price_oracle: address
    monetary_policy: address
    gauge: address

event SetDefaultRates:
    min_rate: uint256
    max_rate: uint256

event SetAdmin:
    admin: address

# TWO events are emitted at market creation because there are two vaults
event NewVault:
    id: indexed(uint256)
    collateral_token: indexed(address)
    borrowed_token: indexed(address)
    vault: address
    controller: address
    amm: address
    price_oracle: address
    monetary_policy: address

event LiquidityGaugeDeployed:
    vault: address
    gauge: address


STABLECOIN: public(immutable(address))

# These are limits for default borrow rates, NOT actual min and max rates.
# Even governance cannot go beyond these rates before a new code is shipped
MIN_RATE: public(constant(uint256)) = 10**15 / (365 * 86400)  # 0.1%
MAX_RATE: public(constant(uint256)) = 10**19 / (365 * 86400)  # 1000%


# Implementations which can be changed by governance
amm_impl: public(address)
controller_impl: public(address)
vault_impl: public(address)
pool_price_oracle_impl: public(address)
wrapper_price_oracle_impl: public(address)
monetary_policy_impl: public(address)
gauge_impl: public(address)

# Actual min/max borrow rates when creating new markets
# for example, 0.5% -> 50% is a good choice
min_default_borrow_rate: public(uint256)
max_default_borrow_rate: public(uint256)

# Admin is supposed to be the DAO
admin: public(address)

# Vaults can only be created but not removed
vaults: public(Vault[10**18])
_vaults_index: HashMap[Vault, uint256]
market_count: public(uint256)

# Index to find vaults by a non-crvUSD token
token_to_vaults: public(HashMap[address, Vault[10**18]])
token_market_count: public(HashMap[address, uint256])

gauges: public(address[10**18])


@external
def __init__(
        stablecoin: address,
        amm: address,
        controller: address,
        vault: address,
        pool_price_oracle: address,
        wrapper_price_oracle: address,
        monetary_policy: address,
        gauge: address,
        admin: address):
    """
    @notice Factory which creates two-way lending vaults (e.g. collateral is borrowable)
    @param stablecoin Address of crvUSD. Only crvUSD-containing markets are allowed
    @param amm Address of AMM implementation
    @param controller Address of Controller implementation
    @param pool_price_oracle Address of implementation for pool price oracle factory (prices from pools)
    @param wrapper_price_oracle Address of implementation for price oracle wrapper factory (multiplies by vault pricePerShare)
    @param monetary_policy Address for implementation of monetary policy
    @param gauge Address for gauge implementation
    @param admin Admin address (DAO)
    """
    STABLECOIN = stablecoin
    self.amm_impl = amm
    self.controller_impl = controller
    self.vault_impl = vault
    self.pool_price_oracle_impl = pool_price_oracle
    self.wrapper_price_oracle_impl = wrapper_price_oracle
    self.monetary_policy_impl = monetary_policy
    self.gauge_impl = gauge

    self.min_default_borrow_rate = 5 * 10**15 / (365 * 86400)
    self.max_default_borrow_rate = 50 * 10**16 / (365 * 86400)

    self.admin = admin


@internal
def _add_to_index(vault: Vault, token_a: address, token_b: address):
    token: address = token_a
    if token_a == STABLECOIN:
        token = token_b
    market_count: uint256 = self.token_market_count[token]
    self.token_to_vaults[token][market_count] = vault
    self.token_market_count[token] = market_count + 1


@internal
def _create(
        vault_long: Vault,
        vault_short: Vault,
        price_oracle_long: address,
        price_oracle_short: address,
        borrowed_token: address,
        collateral_token: address,
        A: uint256,
        fee: uint256,
        loan_discount: uint256,
        liquidation_discount: uint256,
        min_borrow_rate: uint256,
        max_borrow_rate: uint256):
    """
    @notice Internal method for creation of the vault
    """
    assert borrowed_token != collateral_token, "Same token"
    assert borrowed_token == STABLECOIN or collateral_token == STABLECOIN

    min_rate: uint256 = self.min_default_borrow_rate
    max_rate: uint256 = self.max_default_borrow_rate
    if min_borrow_rate > 0:
        min_rate = min_borrow_rate
    if max_borrow_rate > 0:
        max_rate = max_borrow_rate
    assert min_rate >= MIN_RATE and max_rate >= MIN_RATE\
        and min_rate <= MAX_RATE and max_rate <= MAX_RATE\
        and min_rate <= max_rate, "Wrong rates"
    monetary_policy: address = create_from_blueprint(
        self.monetary_policy_impl, borrowed_token, min_rate, max_rate, code_offset=3)

    controller: address = empty(address)
    amm: address = empty(address)
    market_count: uint256 = self.market_count

    controller, amm = vault_long.initialize(
        self.amm_impl, self.controller_impl,
        borrowed_token, vault_short.address,
        A, fee,
        price_oracle_long,
        monetary_policy,
        loan_discount, liquidation_discount
    )

    log NewVault(market_count, vault_short.address, borrowed_token, vault_long.address, controller, amm, price_oracle_long, monetary_policy)
    self.vaults[market_count] = vault_long
    self._vaults_index[vault_long] = market_count + 2**128
    market_count += 1

    controller, amm = vault_short.initialize(
        self.amm_impl, self.controller_impl,
        collateral_token, vault_long.address,
        A, fee,
        price_oracle_short,
        monetary_policy,
        loan_discount, liquidation_discount
    )
    log NewVault(market_count, vault_long.address, collateral_token, vault_short.address, controller, amm, price_oracle_short, monetary_policy)
    self.vaults[market_count] = vault_short
    self._vaults_index[vault_short] = market_count + 2**128
    market_count += 1
    self.market_count = market_count

    self._add_to_index(vault_long, borrowed_token, collateral_token)
    self._add_to_index(vault_short, borrowed_token, collateral_token)


@external
@nonreentrant('lock')
def create(
        borrowed_token: address,
        collateral_token: address,
        A: uint256,
        fee: uint256,
        loan_discount: uint256,
        liquidation_discount: uint256,
        price_oracle: address,
        min_borrow_rate: uint256 = 0,
        max_borrow_rate: uint256 = 0
    ) -> (Vault, Vault):
    """
    @notice Creation of the vault using user-supplied price oracle contract
    @param borrowed_token Token which is being borrowed
    @param collateral_token Token used for collateral
    @param A Amplification coefficient: band size is ~1/A
    @param fee Fee for swaps in AMM (for ETH markets found to be 0.6%)
    @param loan_discount Maximum discount. LTV = sqrt(((A - 1) / A) ** 4) - loan_discount
    @param liquidation_discount Liquidation discount. LT = sqrt(((A - 1) / A) ** 4) - liquidation_discount
    @param price_oracle Custom price oracle contract
    @param min_borrow_rate Custom minimum borrow rate (otherwise min_default_borrow_rate)
    @param max_borrow_rate Custom maximum borrow rate (otherwise max_default_borrow_rate)
    """
    vault_long: Vault = Vault(create_minimal_proxy_to(self.vault_impl))
    vault_short: Vault = Vault(create_minimal_proxy_to(self.vault_impl))

    price_oracle_long: address = create_from_blueprint(
        self.wrapper_price_oracle_impl, price_oracle, vault_short.address, False, code_offset=3)
    price_oracle_short: address = create_from_blueprint(
        self.wrapper_price_oracle_impl, price_oracle, vault_long.address, True, code_offset=3)

    self._create(vault_long, vault_short, price_oracle_long, price_oracle_short,
                 borrowed_token, collateral_token, A, fee, loan_discount, liquidation_discount,
                 min_borrow_rate, max_borrow_rate)

    return (vault_long, vault_short)


@external
@nonreentrant('lock')
def create_from_pool(
        borrowed_token: address,
        collateral_token: address,
        A: uint256,
        fee: uint256,
        loan_discount: uint256,
        liquidation_discount: uint256,
        pool: address,
        min_borrow_rate: uint256 = 0,
        max_borrow_rate: uint256 = 0
    ) -> (Vault, Vault):
    """
    @notice Creation of the vault using existing oraclized Curve pool as a price oracle
    @param borrowed_token Token which is being borrowed
    @param collateral_token Token used for collateral
    @param A Amplification coefficient: band size is ~1/A
    @param fee Fee for swaps in AMM (for ETH markets found to be 0.6%)
    @param loan_discount Maximum discount. LTV = sqrt(((A - 1) / A) ** 4) - loan_discount
    @param liquidation_discount Liquidation discount. LT = sqrt(((A - 1) / A) ** 4) - liquidation_discount
    @param pool Curve tricrypto-ng, twocrypto-ng or stableswap-ng pool which has non-manipulatable price_oracle().
                Must contain both collateral_token and borrowed_token.
    @param min_borrow_rate Custom minimum borrow rate (otherwise min_default_borrow_rate)
    @param max_borrow_rate Custom maximum borrow rate (otherwise max_default_borrow_rate)
    """
    # Find coins in the pool
    borrowed_ix: uint256 = 100
    collateral_ix: uint256 = 100
    N: uint256 = 0
    for i in range(10):
        success: bool = False
        res: Bytes[32] = empty(Bytes[32])
        success, res = raw_call(
            pool,
            _abi_encode(i, method_id=method_id("coins(uint256)")),
            max_outsize=32, is_static_call=True, revert_on_failure=False)
        coin: address = convert(res, address)
        if not success or coin == empty(address):
            break
        N += 1
        if coin == borrowed_token:
            borrowed_ix = i
        elif coin == collateral_token:
            collateral_ix = i
    if collateral_ix == 100 or borrowed_ix == 100:
        raise "Tokens not in pool"
    if N == 2:
        assert Pool(pool).price_oracle() > 0, "Pool has no oracle"
    else:
        assert Pool(pool).price_oracle(0) > 0, "Pool has no oracle"

    vault_long: Vault = Vault(create_minimal_proxy_to(self.vault_impl))
    vault_short: Vault = Vault(create_minimal_proxy_to(self.vault_impl))

    price_oracle_long: address = create_from_blueprint(
        self.pool_price_oracle_impl, pool, N, borrowed_ix, collateral_ix, vault_short.address, code_offset=3)
    price_oracle_short: address = create_from_blueprint(
        self.pool_price_oracle_impl, pool, N, collateral_ix, borrowed_ix, vault_long.address, code_offset=3)

    self._create(vault_long, vault_short, price_oracle_long, price_oracle_short,
                 borrowed_token, collateral_token, A, fee, loan_discount, liquidation_discount,
                 min_borrow_rate, max_borrow_rate)

    return (vault_long, vault_short)


@view
@external
def amms(n: uint256) -> address:
    return self.vaults[n].amm()


@view
@external
def controllers(n: uint256) -> address:
    return self.vaults[n].controller()


@view
@external
def borrowed_tokens(n: uint256) -> address:
    return self.vaults[n].borrowed_token()


@view
@external
def collateral_tokens(n: uint256) -> address:
    return self.vaults[n].collateral_token()


@view
@external
def price_oracles(n: uint256) -> address:
    return self.vaults[n].price_oracle()


@view
@external
def monetary_policies(n: uint256) -> address:
    return Controller(self.vaults[n].controller()).monetary_policy()


@view
@external
def vaults_index(vault: Vault) -> uint256:
    return self._vaults_index[vault] - 2**128


@external
def deploy_gauge(_vault: Vault) -> address:
    """
    @notice Deploy a liquidity gauge for a vault
    @param _vault Vault address to deploy a gauge for
    @return Address of the deployed gauge
    """
    ix: uint256 = self._vaults_index[_vault]
    assert ix != 0, "Unknown vault"
    ix -= 2**128
    assert self.gauges[ix] == empty(address), "Gauge already deployed"
    implementation: address = self.gauge_impl
    assert implementation != empty(address), "Gauge implementation not set"

    gauge: address = create_from_blueprint(implementation, _vault, code_offset=3)
    self.gauges[ix] = gauge

    log LiquidityGaugeDeployed(_vault.address, gauge)
    return gauge


@view
@external
def gauge_for_vault(_vault: Vault) -> address:
    return self.gauges[self._vaults_index[_vault] - 2**128]


@external
@nonreentrant('lock')
def set_implementations(controller: address, amm: address, vault: address,
                        pool_price_oracle: address, wrapper_price_oracle: address, monetary_policy: address,
                        gauge: address):
    """
    @notice Set new implementations (blueprints) for controller, amm, vault, pool price oracle and monetary polcy.
            Doesn't change existing ones
    @param controller Address of the controller blueprint
    @param amm Address of the AMM blueprint
    @param vault Address of the Vault template
    @param pool_price_oracle Address of the pool price oracle blueprint
    @param wrapper_price_oracle Address of the wrapper price oracle blueprint
    @param monetary_policy Address of the monetary policy blueprint
    @param gauge Address for gauge implementation blueprint
    """
    assert msg.sender == self.admin

    if controller != empty(address):
        self.controller_impl = controller
    if amm != empty(address):
        self.amm_impl = amm
    if vault != empty(address):
        self.vault_impl = vault
    if pool_price_oracle != empty(address):
        self.pool_price_oracle_impl = pool_price_oracle
    if wrapper_price_oracle != empty(address):
        self.wrapper_price_oracle_impl = wrapper_price_oracle
    if monetary_policy != empty(address):
        self.monetary_policy_impl = monetary_policy
    if gauge != empty(address):
        self.gauge_impl = gauge

    log SetImplementations(amm, controller, vault, pool_price_oracle, wrapper_price_oracle, monetary_policy, gauge)


@external
@nonreentrant('lock')
def set_default_rates(min_rate: uint256, max_rate: uint256):
    """
    @notice Change min and max default borrow rates for creating new markets
    @param min_rate Minimal borrow rate (0 utilization)
    @param max_rate Maxumum borrow rate (100% utilization)
    """
    assert msg.sender == self.admin

    assert min_rate >= MIN_RATE
    assert max_rate <= MAX_RATE
    assert max_rate >= min_rate

    self.min_default_borrow_rate = min_rate
    self.max_default_borrow_rate = max_rate

    log SetDefaultRates(min_rate, max_rate)


@external
@nonreentrant('lock')
def set_admin(admin: address):
    """
    @notice Set admin of the factory (should end up with DAO)
    @param admin Address of the admin
    """
    assert msg.sender == self.admin
    self.admin = admin
    log SetAdmin(admin)
