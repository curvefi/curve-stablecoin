# @version 0.3.10
"""
@title OneWayLendingFactory
@notice Factory of non-rehypothecated lending vaults: collateral is not being lent out.
       Although Vault.vy allows both, we should have this simpler version and rehypothecating version.
       This version is for L2s: it does not create gauges by itself but uses Gauge Factory to read gauge info.
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
    def amm() -> address: view
    def controller() -> address: view
    def borrowed_token() -> address: view
    def collateral_token() -> address: view
    def price_oracle() -> address: view
    def set_max_supply(_value: uint256): nonpayable

interface Controller:
    def monetary_policy() -> address: view

interface AMM:
    def get_dy(i: uint256, j: uint256, in_amount: uint256) -> uint256: view
    def get_dx(i: uint256, j: uint256, out_amount: uint256) -> uint256: view
    def get_dydx(i: uint256, j: uint256, out_amount: uint256) -> (uint256, uint256): view
    def exchange(i: uint256, j: uint256, in_amount: uint256, min_amount: uint256, _for: address) -> uint256[2]: nonpayable
    def exchange_dy(i: uint256, j: uint256, out_amount: uint256, max_amount: uint256, _for: address) -> uint256[2]: nonpayable

interface Pool:
    def price_oracle(i: uint256 = 0) -> uint256: view  # Universal method!
    def coins(i: uint256) -> address: view

interface GaugeFactory:
    def get_gauge_from_lp_token(addr: address) -> address: view


event SetImplementations:
    amm: address
    controller: address
    vault: address
    price_oracle: address
    monetary_policy: address
    gauge_factory: address

event SetDefaultRates:
    min_rate: uint256
    max_rate: uint256

event SetAdmin:
    admin: address

event NewVault:
    id: indexed(uint256)
    collateral_token: indexed(address)
    borrowed_token: indexed(address)
    vault: address
    controller: address
    amm: address
    price_oracle: address
    monetary_policy: address


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
monetary_policy_impl: public(address)

# Actual min/max borrow rates when creating new markets
# for example, 0.5% -> 50% is a good choice
min_default_borrow_rate: public(uint256)
max_default_borrow_rate: public(uint256)

# Admin is supposed to be the DAO
admin: public(address)

# Vaults can only be created but not removed
vaults: public(Vault[10**18])
amms: public(AMM[10**18])
_vaults_index: HashMap[Vault, uint256]
market_count: public(uint256)

# Index to find vaults by a non-crvUSD token
token_to_vaults: public(HashMap[address, Vault[10**18]])
token_market_count: public(HashMap[address, uint256])

names: public(HashMap[uint256, String[64]])
gauge_factory: public(GaugeFactory)


@external
def __init__(
        stablecoin: address,
        amm: address,
        controller: address,
        vault: address,
        pool_price_oracle: address,
        monetary_policy: address,
        gauge_factory: GaugeFactory,
        admin: address):
    """
    @notice Factory which creates one-way lending vaults (e.g. collateral is non-borrowable)
    @param stablecoin Address of crvUSD. Only crvUSD-containing markets are allowed
    @param amm Address of AMM implementation
    @param controller Address of Controller implementation
    @param pool_price_oracle Address of implementation for price oracle factory (prices from pools)
    @param monetary_policy Address for implementation of monetary policy
    @param gauge_factory Address for gauge factory on this L2
    @param admin Admin address (DAO)
    """
    STABLECOIN = stablecoin
    self.amm_impl = amm
    self.controller_impl = controller
    self.vault_impl = vault
    self.pool_price_oracle_impl = pool_price_oracle
    self.monetary_policy_impl = monetary_policy
    self.gauge_factory = gauge_factory

    self.min_default_borrow_rate = 5 * 10**15 / (365 * 86400)
    self.max_default_borrow_rate = 50 * 10**16 / (365 * 86400)

    self.admin = admin


@internal
def _create(
        borrowed_token: address,
        collateral_token: address,
        A: uint256,
        fee: uint256,
        loan_discount: uint256,
        liquidation_discount: uint256,
        price_oracle: address,
        name: String[64],
        min_borrow_rate: uint256,
        max_borrow_rate: uint256
    ) -> Vault:
    """
    @notice Internal method for creation of the vault
    """
    assert borrowed_token != collateral_token, "Same token"
    assert borrowed_token == STABLECOIN or collateral_token == STABLECOIN
    vault: Vault = Vault(create_minimal_proxy_to(self.vault_impl))

    min_rate: uint256 = self.min_default_borrow_rate
    max_rate: uint256 = self.max_default_borrow_rate
    if min_borrow_rate > 0:
        min_rate = min_borrow_rate
    if max_borrow_rate > 0:
        max_rate = max_borrow_rate
    assert min_rate >= MIN_RATE and max_rate <= MAX_RATE and min_rate <= max_rate, "Wrong rates"
    monetary_policy: address = create_from_blueprint(
        self.monetary_policy_impl, borrowed_token, min_rate, max_rate, code_offset=3)

    controller: address = empty(address)
    amm: address = empty(address)
    controller, amm = vault.initialize(
        self.amm_impl, self.controller_impl,
        borrowed_token, collateral_token,
        A, fee,
        price_oracle,
        monetary_policy,
        loan_discount, liquidation_discount
    )

    market_count: uint256 = self.market_count
    log NewVault(market_count, collateral_token, borrowed_token, vault.address, controller, amm, price_oracle, monetary_policy)
    self.vaults[market_count] = vault
    self.amms[market_count] = AMM(amm)
    self._vaults_index[vault] = market_count + 2**128
    self.names[market_count] = name

    self.market_count = market_count + 1

    token: address = borrowed_token
    if borrowed_token == STABLECOIN:
        token = collateral_token
    market_count = self.token_market_count[token]
    self.token_to_vaults[token][market_count] = vault
    self.token_market_count[token] = market_count + 1

    return vault


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
        name: String[64],
        min_borrow_rate: uint256 = 0,
        max_borrow_rate: uint256 = 0,
        supply_limit: uint256 = max_value(uint256)
    ) -> Vault:
    """
    @notice Creation of the vault using user-supplied price oracle contract
    @param borrowed_token Token which is being borrowed
    @param collateral_token Token used for collateral
    @param A Amplification coefficient: band size is ~1/A
    @param fee Fee for swaps in AMM (for ETH markets found to be 0.6%)
    @param loan_discount Maximum discount. LTV = sqrt(((A - 1) / A) ** 4) - loan_discount
    @param liquidation_discount Liquidation discount. LT = sqrt(((A - 1) / A) ** 4) - liquidation_discount
    @param price_oracle Custom price oracle contract
    @param name Human-readable market name
    @param min_borrow_rate Custom minimum borrow rate (otherwise min_default_borrow_rate)
    @param max_borrow_rate Custom maximum borrow rate (otherwise max_default_borrow_rate)
    @param supply_limit Supply cap
    """
    vault: Vault = self._create(borrowed_token, collateral_token, A, fee, loan_discount, liquidation_discount,
                                price_oracle, name, min_borrow_rate, max_borrow_rate)
    if supply_limit < max_value(uint256):
        vault.set_max_supply(supply_limit)
    return vault


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
        name: String[64],
        min_borrow_rate: uint256 = 0,
        max_borrow_rate: uint256 = 0,
        supply_limit: uint256 = max_value(uint256)
    ) -> Vault:
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
    @param name Human-readable market name
    @param min_borrow_rate Custom minimum borrow rate (otherwise min_default_borrow_rate)
    @param max_borrow_rate Custom maximum borrow rate (otherwise max_default_borrow_rate)
    @param supply_limit Supply cap
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
    price_oracle: address = create_from_blueprint(
        self.pool_price_oracle_impl, pool, N, borrowed_ix, collateral_ix, code_offset=3)

    vault: Vault = self._create(borrowed_token, collateral_token, A, fee, loan_discount, liquidation_discount,
                                price_oracle, name, min_borrow_rate, max_borrow_rate)
    if supply_limit < max_value(uint256):
        vault.set_max_supply(supply_limit)
    return vault


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


@view
@external
def gauge_for_vault(vault: address) -> address:
    out: address = self.gauge_factory.get_gauge_from_lp_token(vault)
    assert out != empty(address)
    return out


@view
@external
def gauges(vault_id: uint256) -> address:
    return self.gauge_factory.get_gauge_from_lp_token(self.vaults[vault_id].address)


@external
@nonreentrant('lock')
def set_implementations(controller: address, amm: address, vault: address,
                        pool_price_oracle: address, monetary_policy: address, gauge_factory: address):
    """
    @notice Set new implementations (blueprints) for controller, amm, vault, pool price oracle and monetary polcy.
            Doesn't change existing ones
    @param controller Address of the controller blueprint
    @param amm Address of the AMM blueprint
    @param vault Address of the Vault template
    @param pool_price_oracle Address of the pool price oracle blueprint
    @param monetary_policy Address of the monetary policy blueprint
    @param gauge_factory Address for gauge factory
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
    if monetary_policy != empty(address):
        self.monetary_policy_impl = monetary_policy
    if gauge_factory != empty(address):
        self.gauge_factory = GaugeFactory(gauge_factory)

    log SetImplementations(amm, controller, vault, pool_price_oracle, monetary_policy, gauge_factory)


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


@external
@view
def coins(vault_id: uint256) -> address[2]:
    vault: Vault = self.vaults[vault_id]
    return [vault.borrowed_token(), vault.collateral_token()]
