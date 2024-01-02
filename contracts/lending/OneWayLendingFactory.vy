# @version 0.3.10
"""
@title Factory of non-rehypothecated lending vaults: collateral is not being lent out.
       Although Vault.vy allows both, we should have this simpler version and rehypothecating version.
@author Curve.fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
"""

# create (low level configuration)
# create_from_pool (with a price oracle)


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
    ) -> address[2]: view

interface Pool:
    def price_oracle(i: uint256 = 0) -> uint256: view  # Universal method!
    def coins(i: uint256) -> address: view


event SetImplementations:
    amm: address
    controller: address
    vault: address
    price_oracle: address
    monetary_policy: address

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


amm_impl: public(address)
controller_impl: public(address)
vault_impl: public(address)
pool_price_oracle_impl: public(address)
monetary_policy_impl: public(address)

min_default_borrow_rate: public(uint256)
max_default_borrow_rate: public(uint256)
admin: public(address)

vaults: public(Vault[10**18])
n_vaults: public(uint256)


@external
def __init__(
        stablecoin: address,
        amm: address,
        controller: address,
        vault: address,
        pool_price_oracle: address,
        monetary_policy: address,
        admin: address):
    STABLECOIN = stablecoin
    self.amm_impl = amm
    self.controller_impl = controller
    self.vault_impl = vault
    self.pool_price_oracle_impl = pool_price_oracle
    self.monetary_policy_impl = monetary_policy

    self.min_default_borrow_rate = 5 * 10**15 / (365 * 86400)
    self.max_default_borrow_rate = 50 * 10**16 / (365 * 86400)

    self.admin = admin


@external
def create():
    pass


@external
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
    ) -> Vault:
    assert borrowed_token != collateral_token, "Same token"
    vault: Vault = Vault(create_minimal_proxy_to(self.vault_impl))

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
    assert N > 1
    if N == 2:
        assert Pool(pool).price_oracle() > 0, "Pool has no oracle"
    else:
        assert Pool(pool).price_oracle(0) > 0, "Pool has no oracle"

    price_oracle: address = create_from_blueprint(
        self.pool_price_oracle_impl, pool, N, borrowed_ix, collateral_ix, code_offset=3)
    monetary_policy: address = create_from_blueprint(self.monetary_policy_impl, vault.address, code_offset=3)

    controller: address = empty(address)
    amm: address = empty(address)
    vault.initialize(
        self.amm_impl, self.controller_impl,
        borrowed_token, collateral_token,
        A, fee,
        price_oracle,
        monetary_policy,
        loan_discount, liquidation_discount
    )

    return vault


@external
def set_implementations(controller: address, amm: address, vault: address,
                        pool_price_oracle: address, monetary_policy: address):
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

    log SetImplementations(amm, controller, vault, pool_price_oracle, monetary_policy)


@external
def set_admin(admin: address):
    """
    @notice Set admin of the factory (should end up with DAO)
    @param admin Address of the admin
    """
    assert msg.sender == self.admin
    self.admin = admin
    log SetAdmin(admin)
