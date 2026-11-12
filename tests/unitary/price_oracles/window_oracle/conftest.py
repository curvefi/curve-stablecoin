import boa
import pytest

from tests.utils.constants import ZERO_ADDRESS
from tests.utils.deployers import WINDOW_ORACLE_DEPLOYER


P0 = 2000 * 10**18
TAU = 1
CAP = 12 * 10**18
STALE = 10**9

# Reports a set price_oracle with a huge ma_time: the oracle takes it as the average
# since its last write as it is
POOL_DEPLOYER = boa.loads_partial("""
# pragma version 0.4.3
coins: public(address[2])
p: uint256


@deploy
def __init__(_coin0: address, _p: uint256):
    self.coins = [_coin0, _coin0]
    self.p = _p


@external
def set_price(_p: uint256):
    self.p = _p


@external
@view
def price_oracle(i: uint256) -> uint256:
    return self.p


@external
@view
def ma_exp_time() -> uint256:
    return 10**14
""")

AGGREGATOR_DEPLOYER = boa.loads_partial("""
# pragma version 0.4.3
stablecoin: public(address)
last_price: public(uint256)
last_timestamp: public(uint256)


@deploy
def __init__(_stablecoin: address):
    self.stablecoin = _stablecoin
    self.last_price = 10**18
    self.last_timestamp = block.timestamp


@external
@view
def price() -> uint256:
    return 10**18


@external
def price_w() -> uint256:
    return 10**18
""")


@pytest.fixture
def p0():
    return P0


@pytest.fixture
def stablecoin():
    return boa.env.generate_address("stablecoin")


@pytest.fixture
def pool(stablecoin):
    return POOL_DEPLOYER.deploy(stablecoin, P0)


@pytest.fixture
def aggregator(stablecoin):
    return AGGREGATOR_DEPLOYER.deploy(stablecoin)


@pytest.fixture
def deploy_window_oracle(pool, aggregator):
    def _deploy(window):
        return WINDOW_ORACLE_DEPLOYER.deploy(
            pool, 0, ZERO_ADDRESS, aggregator, window, TAU, CAP, STALE
        )

    return _deploy
