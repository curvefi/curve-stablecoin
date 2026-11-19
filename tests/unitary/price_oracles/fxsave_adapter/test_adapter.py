import boa
import pytest

from tests.unitary.price_oracles.fxsave_adapter.conftest import (
    FXUSD_PER_FXSP,
    RATE,
    USDC_PER_FXSP,
    WAD,
)


@pytest.mark.parametrize("shares", [0, 1, 10**6, WAD, 123_456 * WAD])
def test_nav(adapter, shares):
    fxsp_shares = shares * RATE // WAD
    fxusd = fxsp_shares * FXUSD_PER_FXSP // WAD
    usdc = fxsp_shares * USDC_PER_FXSP // WAD
    assert adapter.convertToAssets(shares) == fxusd + usdc * 10**12


def test_nav_of_one_share(adapter):
    # Mainnet at block 26,402,887: 0.539072 fxUSD + 0.591116 USDC per fxSAVE.
    assert abs(adapter.convertToAssets(WAD) - 1130188078862358130) <= 1


def test_usdc_counts_as_one_fxusd(adapter, fxsave, fxsp):
    # One fxSP per fxSAVE, backed by exactly one USDC and no fxUSD.
    fxsave.set_rate(WAD)
    fxsp.set_backing(0, 10**6)
    assert adapter.convertToAssets(WAD) == WAD


@pytest.mark.parametrize(
    "upstream, reason", [("fxsave", "fxSAVE unavailable"), ("fxsp", "fxSP unavailable")]
)
def test_upstream_failure_propagates(adapter, fxsave, fxsp, upstream, reason):
    {"fxsave": fxsave, "fxsp": fxsp}[upstream].set_fail(True)
    with boa.reverts(reason):
        adapter.convertToAssets(WAD)
