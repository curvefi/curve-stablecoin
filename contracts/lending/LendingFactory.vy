# pragma version 0.4.3
# pragma optimize codesize
# pragma evm-version shanghai
"""
@title LlamaLend Factory
@notice Factory of non-rehypothecated lending vaults: collateral is not being lent out.
@author Curve.fi
@license Copyright (c) Curve.Fi, 2020-2025 - all rights reserved
"""

from ethereum.ercs import IERC20
from ethereum.ercs import IERC20Detailed
from contracts.interfaces import IVault
from contracts.interfaces import ILlamalendController as IController
from contracts.interfaces import IAMM
from contracts.interfaces import IPool
from contracts.interfaces import IPriceOracle
from contracts.interfaces import ILendingFactory 
implements: ILendingFactory


STABLECOIN: public(immutable(address))

# These are limits for default borrow rates, NOT actual min and max rates.
# Even governance cannot go beyond these rates before a new code is shipped
MIN_RATE: public(constant(uint256)) = 10**15 // (365 * 86400)  # 0.1%
MAX_RATE: public(constant(uint256)) = 10**19 // (365 * 86400)  # 1000%
MIN_A: constant(uint256) = 2
MAX_A: constant(uint256) = 10000
MIN_FEE: constant(uint256) = 10**6  # 1e-12, still needs to be above 0
MAX_FEE: constant(uint256) = 10**17  # 10%
MAX_LOAN_DISCOUNT: constant(uint256) = 5 * 10**17
MIN_LIQUIDATION_DISCOUNT: constant(uint256) = 10**16

# Implementations which can be changed by governance
amm_impl: public(address)
controller_impl: public(address)
vault_impl: public(address)
pool_price_oracle_impl: public(address)
monetary_policy_impl: public(address)

# Actual min//max borrow rates when creating new markets
# for example, 0.5% -> 50% is a good choice
min_default_borrow_rate: public(uint256)
max_default_borrow_rate: public(uint256)

# Admin is supposed to be the DAO
admin: public(address)
fee_receiver: public(address)

# Vaults can only be created but not removed
vaults: public(IVault[10**18])
_vaults_index: HashMap[IVault, uint256]
market_count: public(uint256)

# Index to find vaults by a non-crvUSD token
token_to_vaults: public(HashMap[address, IVault[10**18]])
token_market_count: public(HashMap[address, uint256])

names: public(HashMap[uint256, String[64]])


@deploy
def __init__(
        stablecoin: address,
        amm: address,
        controller: address,
        vault: address,
        pool_price_oracle: address,
        monetary_policy: address,
        admin: address,
        fee_receiver: address,
):
    """
    @notice Factory which creates one-way lending vaults (e.g. collateral is non-borrowable)
    @param stablecoin Address of crvUSD. Only crvUSD-containing markets are allowed
    @param amm Address of AMM implementation
    @param controller Address of Controller implementation
    @param pool_price_oracle Address of implementation for price oracle factory (prices from pools)
    @param monetary_policy Address for implementation of monetary policy
    @param admin Admin address (DAO)
    @param fee_receiver Receiver of interest and admin fees
    """
    STABLECOIN = stablecoin
    self.amm_impl = amm
    self.controller_impl = controller
    self.vault_impl = vault
    self.pool_price_oracle_impl = pool_price_oracle
    self.monetary_policy_impl = monetary_policy

    self.min_default_borrow_rate = 5 * 10**15 // (365 * 86400)
    self.max_default_borrow_rate = 50 * 10**16 // (365 * 86400)

    self.admin = admin
    self.fee_receiver = fee_receiver


# TODO use snekmate's 
@internal
@pure
def ln_int(_x: uint256) -> int256:
    """
    @notice Logarithm ln() function based on log2. Not very gas-efficient but brief
    """
    # adapted from: https://medium.com//coinmonks//9aef8515136e
    # and vyper log implementation
    # This can be much more optimal but that's not important here
    x: uint256 = _x
    res: uint256 = 0
    for i: uint256 in range(8):
        t: uint256 = 2**(7 - i)
        p: uint256 = 2**t
        if x >= p * 10**18:
            x //= p
            res += t * 10**18
    d: uint256 = 10**18
    for i: uint256 in range(59):  # 18 decimals: math.log2(10**10) == 59.7
        if (x >= 2 * 10**18):
            res += d
            x //= 2
        x = x * x // 10**18
        d //= 2
    # Now res = log2(x)
    # ln(x) = log2(x) // log2(e)
    return convert(res * 10**18 // 1442695040888963328, int256)


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
    ) -> address[3]:
    """
    @notice Internal method for creation of the vault
    """
    assert borrowed_token != collateral_token, "Same token"
    assert borrowed_token == STABLECOIN or collateral_token == STABLECOIN
    assert A >= MIN_A and A <= MAX_A, "Wrong A"
    assert fee <= MAX_FEE, "Fee too high"
    assert fee >= MIN_FEE, "Fee too low"
    assert liquidation_discount >= MIN_LIQUIDATION_DISCOUNT, "Liquidation discount too low"
    assert loan_discount <= MAX_LOAN_DISCOUNT, "Loan discount too high"
    assert loan_discount > liquidation_discount, "need loan_discount>liquidation_discount"

    min_rate: uint256 = self.min_default_borrow_rate
    max_rate: uint256 = self.max_default_borrow_rate
    if min_borrow_rate > 0:
        min_rate = min_borrow_rate
    if max_borrow_rate > 0:
        max_rate = max_borrow_rate
    assert min_rate >= MIN_RATE and max_rate <= MAX_RATE and min_rate <= max_rate, "Wrong rates"
    monetary_policy: address = create_from_blueprint(
        self.monetary_policy_impl, borrowed_token, min_rate, max_rate, code_offset=3)

    A_ratio: uint256 = 10**18 * A // (A - 1)
    p: uint256 = staticcall IPriceOracle(price_oracle).price()  # This also validates price oracle ABI
    assert p > 0
    assert extcall IPriceOracle(price_oracle).price_w() == p

    vault: IVault = IVault(create_minimal_proxy_to(self.vault_impl))
    amm: address = create_from_blueprint(
        self.amm_impl,
        borrowed_token, 10**convert(18 - staticcall IERC20Detailed(borrowed_token).decimals(), uint256),
        collateral_token, 10**convert(18 - staticcall IERC20Detailed(collateral_token).decimals(), uint256),
        A, isqrt(A_ratio * 10**18), self.ln_int(A_ratio),
        p, fee, convert(0, uint256), price_oracle,
        code_offset=3)
    controller: address = create_from_blueprint(
        self.controller_impl,
        vault, amm,
        borrowed_token, collateral_token,
        monetary_policy, loan_discount, liquidation_discount,
        code_offset=3)
    extcall IAMM(amm).set_admin(controller)

    extcall vault.initialize(IAMM(amm), controller, IERC20(borrowed_token), IERC20(collateral_token))

    market_count: uint256 = self.market_count
    log ILendingFactory.NewVault(
        id=market_count,
        collateral_token=collateral_token,
        borrowed_token=borrowed_token,
        vault=vault.address,
        controller=controller,
        amm=amm,
        price_oracle=price_oracle,
        monetary_policy=monetary_policy
    )
    self.vaults[market_count] = vault
    self._vaults_index[vault] = market_count + 2**128
    self.names[market_count] = name

    self.market_count = market_count + 1

    token: address = borrowed_token
    if borrowed_token == STABLECOIN:
        token = collateral_token
    market_count = self.token_market_count[token]
    self.token_to_vaults[token][market_count] = vault
    self.token_market_count[token] = market_count + 1

    return [vault.address, controller, amm]


@external
@nonreentrant
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
    ) -> address[3]:
    """
    @notice Creation of the vault using user-supplied price oracle contract
    @param borrowed_token Token which is being borrowed
    @param collateral_token Token used for collateral
    @param A Amplification coefficient: band size is ~1//A
    @param fee Fee for swaps in AMM (for ETH markets found to be 0.6%)
    @param loan_discount Maximum discount. LTV = sqrt(((A - 1) // A) ** 4) - loan_discount
    @param liquidation_discount Liquidation discount. LT = sqrt(((A - 1) // A) ** 4) - liquidation_discount
    @param price_oracle Custom price oracle contract
    @param name Human-readable market name
    @param min_borrow_rate Custom minimum borrow rate (otherwise min_default_borrow_rate)
    @param max_borrow_rate Custom maximum borrow rate (otherwise max_default_borrow_rate)
    @param supply_limit Supply cap
    """
    res: address[3] = self._create(borrowed_token, collateral_token, A, fee, loan_discount, liquidation_discount,
                                price_oracle, name, min_borrow_rate, max_borrow_rate)
    if supply_limit < max_value(uint256):
        extcall IVault(res[0]).set_max_supply(supply_limit)

    return res


@external
@nonreentrant
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
    ) -> address[3]:
    """
    @notice Creation of the vault using existing oraclized Curve pool as a price oracle
    @param borrowed_token Token which is being borrowed
    @param collateral_token Token used for collateral
    @param A Amplification coefficient: band size is ~1//A
    @param fee Fee for swaps in AMM (for ETH markets found to be 0.6%)
    @param loan_discount Maximum discount. LTV = sqrt(((A - 1) // A) ** 4) - loan_discount
    @param liquidation_discount Liquidation discount. LT = sqrt(((A - 1) // A) ** 4) - liquidation_discount
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
    for i: uint256 in range(10):
        success: bool = False
        res: Bytes[32] = empty(Bytes[32])
        success, res = raw_call(
            pool,
            abi_encode(i, method_id=method_id("coins(uint256)")),
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

    res: address[3] = self._create(
        borrowed_token, collateral_token, A, fee, loan_discount, liquidation_discount,
        price_oracle, name, min_borrow_rate, max_borrow_rate,
    )
    if supply_limit < max_value(uint256):
        extcall IVault(res[0]).set_max_supply(supply_limit)

    return res


@view
@external
def controllers(n: uint256) -> address:
    return staticcall self.vaults[n].controller()


@view
@external
def amms(n: uint256) -> address:
    return (staticcall self.vaults[n].amm()).address


@view
@external
def borrowed_tokens(n: uint256) -> address:
    return (staticcall self.vaults[n].borrowed_token()).address


@view
@external
def collateral_tokens(n: uint256) -> address:
    return (staticcall self.vaults[n].collateral_token()).address


@view
@external
def price_oracles(n: uint256) -> address:
    return (staticcall (staticcall self.vaults[n].amm()).price_oracle_contract()).address


@view
@external
def monetary_policies(n: uint256) -> address:
    return (staticcall IController(staticcall self.vaults[n].controller()).monetary_policy()).address


@view
@external
def vaults_index(vault: IVault) -> uint256:
    return self._vaults_index[vault] - 2**128


@external
@nonreentrant
def set_implementations(controller: address, amm: address, vault: address,
                        pool_price_oracle: address, monetary_policy: address):
    """
    @notice Set new implementations (blueprints) for controller, amm, vault, pool price oracle and monetary polcy.
            Doesn't change existing ones
    @param controller Address of the controller blueprint
    @param amm Address of the AMM blueprint
    @param vault Address of the Vault template
    @param pool_price_oracle Address of the pool price oracle blueprint
    @param monetary_policy Address of the monetary policy blueprint
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

    log ILendingFactory.SetImplementations(
        amm=amm,
        controller=controller,
        vault=vault,
        price_oracle=pool_price_oracle,
        monetary_policy=monetary_policy
    )


@external
@nonreentrant
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

    log ILendingFactory.SetDefaultRates(min_rate=min_rate, max_rate=max_rate)


@external
@nonreentrant
def set_admin(admin: address):
    """
    @notice Set admin of the factory (should end up with DAO)
    @param admin Address of the admin
    """
    assert msg.sender == self.admin
    self.admin = admin
    log ILendingFactory.SetAdmin(admin=admin)


@external
@nonreentrant
def set_fee_receiver(fee_receiver: address):
    """
    @notice Set fee receiver who earns interest (DAO)
    @param fee_receiver Address of the receiver
    """
    assert msg.sender == self.admin
    assert fee_receiver != empty(address)
    self.fee_receiver = fee_receiver
    log ILendingFactory.SetFeeReceiver(fee_receiver=fee_receiver)


@external
@view
def coins(vault_id: uint256) -> address[2]:
    vault: IVault = self.vaults[vault_id]
    return [(staticcall vault.borrowed_token()).address, (staticcall vault.collateral_token()).address]
