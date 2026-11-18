import boa
import pytest

from tests.utils.deployers import REUSD_CRVUSD_ADAPTER_DEPLOYER


FEED_ADDRESS = "0x07Ac1E016D4335FB833666ed5C43846162d2B7e8"
WAD = 10**18

# Only the crvUSD entrypoint exists: accidentally calling price() must fail.
FEED_DEPLOYER = boa.loads_partial("""
# pragma version 0.4.3
value: public(uint256)
fail: public(bool)

@external
def set_value(_value: uint256):
    self.value = _value

@external
def set_fail(fail: bool):
    self.fail = fail

@external
@view
def priceAsCrvusd() -> uint256:
    assert not self.fail, "feed unavailable"
    return self.value
""")


@pytest.fixture
def feed():
    with boa.env.anchor():
        mock = FEED_DEPLOYER.deploy(override_address=FEED_ADDRESS)
        mock.set_value(WAD)
        yield mock


@pytest.fixture
def adapter(feed):
    return REUSD_CRVUSD_ADAPTER_DEPLOYER.deploy()
