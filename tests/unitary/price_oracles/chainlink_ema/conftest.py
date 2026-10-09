import boa
import pytest
import solcx
from boa_solidity.soldeployer import SolDeployer

from tests.utils.deployers import PRICE_ORACLES_CONTRACT_PATH


OBSERVATIONS = 20
INTERVAL = 30
MAX_LOOKBACK = OBSERVATIONS * 2
SMOOTHING_FACTOR = 2 * 10**18 // (OBSERVATIONS + 1)
FEED_DECIMALS = 8
PRECISION_MUL = 10 ** (18 - FEED_DECIMALS)

solcx.install_solc("0.8.25")
# solc reports sources relative to the cwd, so pick the contract by name rather than path
_compiled = solcx.compile_files(
    [PRICE_ORACLES_CONTRACT_PATH / "ChainlinkEMA.sol"],
    output_values=["abi", "bin"],
    solc_version="0.8.25",
)
_chainlink_ema = next(v for k, v in _compiled.items() if k.endswith(":ChainlinkEMA"))
CHAINLINK_EMA_DEPLOYER = SolDeployer(
    _chainlink_ema["abi"], bytes.fromhex(_chainlink_ema["bin"])
)

# Models an EACAggregatorProxy whose aggregators can run in parallel before the proxy
# switches phase. Matches what the real proxy returns on Optimism: a round past the end
# of an existing phase comes back zeroed, a phase with no aggregator reverts.
FEED_DEPLOYER = boa.loads_partial("""
# pragma version 0.4.3

struct Round:
    answer: int256
    updated_at: uint256

decimals: public(uint8)
phaseId: public(uint16)
last_round: public(HashMap[uint16, uint256])
rounds: HashMap[uint16, HashMap[uint256, Round]]


@deploy
def __init__(_decimals: uint8):
    self.decimals = _decimals
    self.phaseId = 1


@external
def add_rounds(_phase: uint16, _answer: int256, _start: uint256, _step: uint256, _count: uint256):
    n: uint256 = self.last_round[_phase]
    for i: uint256 in range(_count, bound=10000):
        n += 1
        self.rounds[_phase][n] = Round(answer=_answer, updated_at=_start + i * _step)
    self.last_round[_phase] = n


@external
def set_phase(_phase: uint16):
    self.phaseId = _phase


@internal
@view
def _round_data(_phase: uint16, _round: uint256) -> (uint80, int256, uint256, uint256, uint80):
    round_id: uint80 = convert((convert(_phase, uint256) << 64) | _round, uint80)
    if _round == 0 or _round > self.last_round[_phase]:
        return round_id, 0, 0, 0, round_id
    r: Round = self.rounds[_phase][_round]
    return round_id, r.answer, r.updated_at, r.updated_at, round_id


@external
@view
def latestRoundData() -> (uint80, int256, uint256, uint256, uint80):
    return self._round_data(self.phaseId, self.last_round[self.phaseId])


@external
@view
def getRoundData(_round_id: uint80) -> (uint80, int256, uint256, uint256, uint80):
    phase: uint16 = convert(convert(_round_id, uint256) >> 64, uint16)
    assert phase != 0 and phase <= self.phaseId, "no aggregator"
    return self._round_data(phase, convert(_round_id, uint256) & convert(max_value(uint64), uint256))
""")


def observation(timestamp):
    return timestamp // INTERVAL * INTERVAL


def next_ema(price, ema):
    return (price * SMOOTHING_FACTOR + ema * (10**18 - SMOOTHING_FACTOR)) // 10**18


def sample(rounds, obs):
    # the answer live at an observation is the last round updated strictly before it
    return [answer for answer, updated_at in rounds if updated_at < obs][-1]


@pytest.fixture
def feed():
    return FEED_DEPLOYER.deploy(FEED_DECIMALS)


@pytest.fixture
def deploy_oracle(feed):
    def f():
        return CHAINLINK_EMA_DEPLOYER.deploy(feed.address, OBSERVATIONS, INTERVAL)

    return f
