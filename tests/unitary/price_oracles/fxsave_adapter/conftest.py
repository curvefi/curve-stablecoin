import boa
import pytest

from tests.utils.deployers import FXSAVE_ADAPTER_DEPLOYER

FXSAVE_ADDRESS = "0x7743e50F534a7f9F1791DdE7dCD89F7783Eefc39"
FXSP_ADDRESS = "0x65C9A641afCEB9C0E6034e558A319488FA0FA3be"
WAD = 10**18

# Mainnet at block 26,402,887: fxSP per fxSAVE, then fxUSD (18 decimals) and
# USDC (6 decimals) per fxSP.
RATE = 1118595731978976327
FXUSD_PER_FXSP = 481918590828746188
USDC_PER_FXSP = 528445

# convertToAssets(shares) == shares * rate / 1e18, in fxSP.
FXSAVE_DEPLOYER = boa.loads_partial("""
# pragma version 0.4.3
rate: public(uint256)
fail: public(bool)

@external
def set_rate(_rate: uint256):
    self.rate = _rate

@external
def set_fail(_fail: bool):
    self.fail = _fail

@external
@view
def convertToAssets(_shares: uint256) -> uint256:
    assert not self.fail, "fxSAVE unavailable"
    return _shares * self.rate // 10**18
""")

# previewRedeem(shares) == pro-rata (fxUSD, USDC).
FXSP_DEPLOYER = boa.loads_partial("""
# pragma version 0.4.3
fxusd_per_share: public(uint256)
usdc_per_share: public(uint256)
fail: public(bool)

@external
def set_backing(_fxusd_per_share: uint256, _usdc_per_share: uint256):
    self.fxusd_per_share = _fxusd_per_share
    self.usdc_per_share = _usdc_per_share

@external
def set_fail(_fail: bool):
    self.fail = _fail

@external
@view
def previewRedeem(_shares: uint256) -> (uint256, uint256):
    assert not self.fail, "fxSP unavailable"
    return (
        _shares * self.fxusd_per_share // 10**18,
        _shares * self.usdc_per_share // 10**18,
    )
""")


@pytest.fixture
def fxsave():
    with boa.env.anchor():
        mock = FXSAVE_DEPLOYER.deploy(override_address=FXSAVE_ADDRESS)
        mock.set_rate(RATE)
        yield mock


@pytest.fixture
def fxsp():
    with boa.env.anchor():
        mock = FXSP_DEPLOYER.deploy(override_address=FXSP_ADDRESS)
        mock.set_backing(FXUSD_PER_FXSP, USDC_PER_FXSP)
        yield mock


@pytest.fixture
def adapter(fxsave, fxsp):
    return FXSAVE_ADAPTER_DEPLOYER.deploy()
