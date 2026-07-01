from pathlib import Path

import boa
import pytest


WAD = 10**18
MIN_LIQUIDITY = 100_000 * WAD
COMPILER_ARGS_DEFAULT = {"experimental_codegen": False}


AGGREGATE_STABLE_PRICE4_DEPLOYER = boa.load_partial(
    Path("curve_stablecoin/price_oracles/aggregate_stable_price/AggregateStablePrice4.vy"),
    compiler_args=COMPILER_ARGS_DEFAULT,
)
ERC20_MOCK_DEPLOYER = boa.load_partial(
    Path("curve_stablecoin/testing/ERC20Mock.vy"),
    compiler_args=COMPILER_ARGS_DEFAULT,
)

OLD_POOL_DEPLOYER = boa.loads_partial(
    """
# pragma version 0.4.3

ADMIN: immutable(address)
coins: public(immutable(address[2]))
price_oracle: public(uint256)
get_virtual_price: public(uint256)
totalSupply: public(uint256)

@deploy
def __init__(
    _admin: address,
    _coin0: address,
    _coin1: address,
    _price: uint256,
    _total_supply: uint256,
    _virtual_price: uint256,
):
    ADMIN = _admin
    coins = [_coin0, _coin1]
    self.price_oracle = _price
    self.totalSupply = _total_supply
    self.get_virtual_price = _virtual_price

@external
def set_price(_price: uint256):
    assert msg.sender == ADMIN
    self.price_oracle = _price

@external
def set_tvl(_total_supply: uint256, _virtual_price: uint256):
    assert msg.sender == ADMIN
    self.totalSupply = _total_supply
    self.get_virtual_price = _virtual_price
    """,
    name="AggStableOldPoolMock",
)

NG_POOL_DEPLOYER = boa.loads_partial(
    """
# pragma version 0.4.3

ADMIN: immutable(address)
coins: public(immutable(address[2]))
price: public(uint256)
D_oracle: public(uint256)
totalSupply: public(uint256)
get_virtual_price: public(uint256)

@deploy
def __init__(
    _admin: address,
    _coin0: address,
    _coin1: address,
    _price: uint256,
    _d_oracle: uint256,
):
    ADMIN = _admin
    coins = [_coin0, _coin1]
    self.price = _price
    self.D_oracle = _d_oracle
    self.totalSupply = _d_oracle
    self.get_virtual_price = 10**18

@external
@view
def price_oracle(i: uint256=0) -> uint256:
    return self.price

@external
def set_price(_price: uint256):
    assert msg.sender == ADMIN
    self.price = _price

@external
def set_tvl(_d_oracle: uint256):
    assert msg.sender == ADMIN
    self.D_oracle = _d_oracle
    self.totalSupply = _d_oracle
    """,
    name="AggStableNGPoolMock",
)

CAPPED_SHARE_HARNESS_DEPLOYER = boa.loads_partial(
    """
# pragma version 0.4.3

from curve_stablecoin.price_oracles.aggregate_stable_price import capped_share

initializes: capped_share
exports: capped_share.custom_share_cap


@deploy
def __init__():
    pass


@external
@pure
def default_cap(n_active: uint256) -> uint256:
    return capped_share._default_cap(n_active)


@external
@view
def share_cap(n_active: uint256) -> uint256:
    return capped_share.share_cap(n_active)


@external
def set_share_cap(_share_cap: uint256):
    capped_share.set_custom_share_cap(_share_cap)


@external
@view
def capped_weights(D: DynArray[uint256, 64]) -> DynArray[uint256, 64]:
    return capped_share.capped_weights(D)
    """,
    name="AggStableCappedShareHarness",
)

WEIGHTED_PRICE_HARNESS_DEPLOYER = boa.loads_partial(
    """
# pragma version 0.4.3

from curve_stablecoin.price_oracles.aggregate_stable_price import weighted_price

initializes: weighted_price
exports: weighted_price.sigma


@deploy
def __init__(_sigma: uint256):
    weighted_price.__init__(_sigma)


@external
@pure
def weighted_avg(
    prices: DynArray[uint256, 64],
    weights: DynArray[uint256, 64]
) -> uint256:
    return weighted_price.weighted_avg(prices, weights)


@external
@view
def exp_penalized_price(
    prices: DynArray[uint256, 64],
    weights: DynArray[uint256, 64],
    p_ref: uint256
) -> uint256:
    return weighted_price.exp_penalized_price(prices, weights, p_ref)
    """,
    name="AggStableWeightedPriceHarness",
)


@pytest.fixture(scope="module")
def agg_deployer():
    return AGGREGATE_STABLE_PRICE4_DEPLOYER


@pytest.fixture(scope="module")
def capped_share_deployer():
    return CAPPED_SHARE_HARNESS_DEPLOYER


@pytest.fixture(scope="module")
def weighted_price_deployer():
    return WEIGHTED_PRICE_HARNESS_DEPLOYER


@pytest.fixture(scope="module")
def admin():
    return boa.env.generate_address("agg_admin")


@pytest.fixture(scope="module")
def emergency_admin():
    return boa.env.generate_address("agg_emergency_admin")


@pytest.fixture(scope="module")
def alice():
    return boa.env.generate_address("agg_alice")


@pytest.fixture(scope="module")
def stablecoin(admin):
    with boa.env.prank(admin):
        return ERC20_MOCK_DEPLOYER.deploy(18)


@pytest.fixture(scope="module")
def redeemable(admin):
    with boa.env.prank(admin):
        return ERC20_MOCK_DEPLOYER.deploy(18)


@pytest.fixture(scope="module")
def other_token(admin):
    with boa.env.prank(admin):
        return ERC20_MOCK_DEPLOYER.deploy(18)


@pytest.fixture
def agg(agg_deployer, stablecoin, admin, emergency_admin):
    with boa.env.prank(admin):
        return agg_deployer.deploy(stablecoin.address, 10**16, admin, emergency_admin)


@pytest.fixture
def capped_share(capped_share_deployer):
    return capped_share_deployer.deploy()


@pytest.fixture
def weighted_price(weighted_price_deployer):
    return weighted_price_deployer.deploy(10**16)


@pytest.fixture
def old_pool_factory(admin, stablecoin, redeemable):
    def deploy(
        price=WAD,
        tvl=MIN_LIQUIDITY * 2,
        virtual_price=WAD,
        stable_ix=1,
        token=None,
    ):
        paired_token = token or redeemable
        coins = [paired_token.address, stablecoin.address]
        if stable_ix == 0:
            coins = [stablecoin.address, paired_token.address]
        with boa.env.prank(admin):
            return OLD_POOL_DEPLOYER.deploy(
                admin, coins[0], coins[1], price, tvl, virtual_price
            )

    return deploy


@pytest.fixture
def ng_pool_factory(admin, stablecoin, redeemable):
    def deploy(price=WAD, tvl=MIN_LIQUIDITY * 2, stable_ix=1, token=None):
        paired_token = token or redeemable
        coins = [paired_token.address, stablecoin.address]
        if stable_ix == 0:
            coins = [stablecoin.address, paired_token.address]
        with boa.env.prank(admin):
            return NG_POOL_DEPLOYER.deploy(admin, coins[0], coins[1], price, tvl)

    return deploy
