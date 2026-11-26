"""Fixtures for DeltaPPSRateCalculator unit tests.

The calculator's only external collaborator is the ERC4626 vault, read through
`convertToAssets`. It is mocked inline with a settable price-per-share
(pps == assets for one whole 1e18 share), so tests can drive the PPS
directly instead of forking mainnet.
"""

import boa
import pytest

from tests.utils.deployers import DELTA_PPS_RATE_CALCULATOR_DEPLOYER

WAD = 10**18
DAY = 86400

# Inline ERC4626 vault stand-in: convertToAssets(shares) == shares * pps / 1e18.
_VAULT_MOCK = """
WAD: constant(uint256) = 10**18

pps: public(uint256)

@deploy
def __init__(_pps: uint256):
    self.pps = _pps

@external
@view
def convertToAssets(_shares: uint256) -> uint256:
    return _shares * self.pps // WAD

@external
def set_pps(_pps: uint256):
    self.pps = _pps
"""


@pytest.fixture
def vault():
    """Fresh vault mock, seeded at 1:1 pps (tests set it explicitly)."""
    return boa.loads(_VAULT_MOCK, WAD)


@pytest.fixture
def rate_calc(vault):
    """Fresh DeltaPPSRateCalculator wired to the mock."""
    return DELTA_PPS_RATE_CALCULATOR_DEPLOYER.deploy(vault.address)


@pytest.fixture
def buffer_of():
    """Read the full 7-slot pps_records ring buffer as [(pps, ts), ...]."""

    def _read(rc):
        return [tuple(rc.pps_records(i)) for i in range(7)]

    return _read


@pytest.fixture
def step():
    """Advance the calculator one 'day': set env time + pps, then call rate_w().

    Also asserts the read-only rate() returns the same value rate_w() then returns
    at the same block, giving rate()/rate_w() equivalence coverage across every
    scenario in this package.

    Returns the rate_w() return value.
    """

    def _step(rate_calc, vault, ts, pps):
        boa.env.evm.patch.timestamp = ts
        vault.set_pps(pps)

        rate_view = rate_calc.rate()  # @view: cannot mutate pps_records
        rate_write = rate_calc.rate_w()
        assert rate_view == rate_write, "rate() != rate_w()"
        return rate_write

    return _step
