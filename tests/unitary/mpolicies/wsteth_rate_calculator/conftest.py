"""Fixtures for WstETHRateCalculator unit tests.

The calculator's only external collaborator is Lido's wstETH TokenRateOracle on the
L2. It is mocked inline as an append-only list of (rate, rateUpdatedL1Timestamp)
entries. The mock reports rateReceivedL2Timestamp 1-3 hours after the L1 timestamp,
varying per entry as on the real oracle, so a calculator reading the wrong field would
be caught.
"""

import boa
import pytest

from tests.utils.deployers import (
    MPOLICIES_CONTRACT_PATH,
    WSTETH_RATE_CALCULATOR_DEPLOYER,
)

DAY = 86400
WINDOW = 7 * DAY
RATE_PRECISION = 10**27  # Lido reports the wstETH/stETH rate with 27 decimals
T0 = 1_700_000_000  # arbitrary first report timestamp for synthetic scenarios

# Recorded from Lido's TokenRateOracle on Optimism
# (0x294ED1f214F4e0ecAE31C3Eae4F04EBB3b36C9d0), entries 731-745 on 2026-10-22:
# (tokenRate, rateUpdatedL1Timestamp)
LIDO_OPTIMISM_RATES = [
    (1245861716930919999045431092, 1791460811),
    (1245938079126728715395035859, 1791547211),
    (1246013674805236042782740941, 1791633611),
    (1246088839423097632100680673, 1791720011),
    (1246164530430603438421137028, 1791806411),
    (1246241142059868295424911366, 1791892811),
    (1246316517415262462753394569, 1791979211),
    (1246393484391905431041994810, 1792065611),
    (1246469468402524072094952059, 1792152011),
    (1246544840943039301388773777, 1792238411),
    (1246620093818911326711436917, 1792324811),
    (1246695894222031964196075534, 1792411211),
    (1246771858911220488232383686, 1792497611),
    (1246848066199715680180129215, 1792584011),
    (1246925215523518288853963597, 1792670411),
]

_ORACLE_MOCK = """
# pragma version 0.4.3

rates: DynArray[uint256, 1000]
timestamps: DynArray[uint256, 1000]


@external
def push(_rate: uint256, _ts: uint256):
    self.rates.append(_rate)
    self.timestamps.append(_ts)


@external
def pop():
    self.rates.pop()
    self.timestamps.pop()


@external
@view
def getTokenRatesLength() -> uint256:
    return len(self.rates)


@external
@view
def getTokenRateByIndex(_index: uint256) -> (uint256, uint256, uint256):
    # the rate reaches the L2 1-3 hours after the L1 report, varying per entry
    return self.rates[_index], self.timestamps[_index], self.timestamps[_index] + (_index % 3 + 1) * 3600
"""

# The calculator live on Optimism before the move to the v2 monetary policy.
LEGACY_CALCULATOR_DEPLOYER = boa.load_partial(
    MPOLICIES_CONTRACT_PATH / "wstETHRateCalculator.vy"
)


def expected_rate(entries, window=WINDOW):
    """Reference implementation: growth over the entry `window // DAY` places back."""
    days_back = window // DAY
    if len(entries) <= days_back:
        return 0
    r_latest, ts_latest = entries[-1]
    r_oldest, ts_oldest = entries[-1 - days_back]
    if ts_latest <= ts_oldest or r_latest <= r_oldest:
        return 0
    return (r_latest - r_oldest) * 10**18 // r_oldest // (ts_latest - ts_oldest)


def daily_entries(n, apr=0.03, start_rate=12 * RATE_PRECISION // 10, start_ts=T0):
    """n daily (rate, ts) entries compounding at `apr`."""
    growth = 1 + apr / 365
    return [(int(start_rate * growth**i), start_ts + i * DAY) for i in range(n)]


@pytest.fixture
def oracle():
    return boa.loads(_ORACLE_MOCK)


@pytest.fixture
def push():
    def _push(oracle, entries):
        for rate, ts in entries:
            oracle.push(rate, ts)

    return _push


@pytest.fixture
def deploy_calculator():
    def _deploy(oracle, window=WINDOW):
        return WSTETH_RATE_CALCULATOR_DEPLOYER.deploy(oracle.address, window)

    return _deploy
