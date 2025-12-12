# pragma version 0.4.3
# pragma nonreentrancy on
"""
@title Create From Pool Factory Helper
@notice Disposable contract to create lending markets using existing Curve pools as price oracles.
    Needs to be redeployed to change pool_price_oracle_blueprint.
@author Curve.fi
@license Copyright (c) Curve.Fi, 2020-2025 - all rights reserved
@custom:security security@curve.fi
"""
from curve_std.interfaces import IERC20
from curve_stablecoin.interfaces import ILendingFactory
from curve_stablecoin.interfaces import IMonetaryPolicy
from curve_stablecoin.interfaces import IPriceOracle

FACTORY: immutable(ILendingFactory)
POOL_PRICE_ORACLE_BLUEPRINT: public(immutable(address))


@deploy
def __init__(_factory: ILendingFactory, _pool_price_oracle_blueprint: address):
    FACTORY = _factory
    POOL_PRICE_ORACLE_BLUEPRINT = _pool_price_oracle_blueprint


@external
def create_from_pool(
    _borrowed_token: IERC20,
    _collateral_token: IERC20,
    _A: uint256,
    _fee: uint256,
    _loan_discount: uint256,
    _liquidation_discount: uint256,
    _monetary_policy: IMonetaryPolicy,
    _pool: address,
    _name: String[64],
    _supply_limit: uint256 = max_value(uint256),
) -> address[3]:
    """
    @notice Creation of the vault using existing oraclized Curve pool as a price oracle
    @param _borrowed_token Token which is being borrowed
    @param _collateral_token Token used for collateral
    @param _A Amplification coefficient: band size is ~1//A
    @param _fee Fee for swaps in AMM (for ETH markets found to be 0.6%)
    @param _loan_discount Maximum discount. LTV = sqrt(((A - 1) // A) ** 4) - loan_discount
    @param _liquidation_discount Liquidation discount. LT = sqrt(((A - 1) // A) ** 4) - liquidation_discount
    @param _monetary_policy Monetary policy contract for the market
    @param _pool Curve tricrypto-ng, twocrypto-ng or stableswap-ng pool which has non-manipulatable price_oracle().
                Must contain both collateral_token and borrowed_token.
    @param _name Human-readable market name
    @param _supply_limit Supply cap
    """
    # Find coins in the pool
    borrowed_ix: uint256 = 100
    collateral_ix: uint256 = 100
    # TODO duplicated code
    N: uint256 = 0
    for i: uint256 in range(10):
        success: bool = False
        res: Bytes[32] = empty(Bytes[32])
        success, res = raw_call(
            _pool,
            abi_encode(i, method_id=method_id("coins(uint256)")),
            max_outsize=32,
            is_static_call=True,
            revert_on_failure=False,
        )
        coin: IERC20 = IERC20(convert(res, address))
        if not success or coin == empty(IERC20):
            break
        N += 1
        if coin == _borrowed_token:
            borrowed_ix = i
        elif coin == _collateral_token:
            collateral_ix = i
    if collateral_ix == 100 or borrowed_ix == 100:
        raise "Tokens not in pool"
    price_oracle: IPriceOracle = IPriceOracle(
        create_from_blueprint(POOL_PRICE_ORACLE_BLUEPRINT, _pool, N, borrowed_ix, collateral_ix)
    )

    res: address[3] = extcall FACTORY.create(
        _borrowed_token,
        _collateral_token,
        _A,
        _fee,
        _loan_discount,
        _liquidation_discount,
        price_oracle,
        _monetary_policy,
        _name,
        _supply_limit,
    )

    return res
