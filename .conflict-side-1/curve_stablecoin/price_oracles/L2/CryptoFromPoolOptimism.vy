# @version 0.3.10
"""
@title CryptoFromPool
@notice Price oracle for pools which contain cryptos and crvUSD. This is NOT suitable for minted crvUSD - only for lent out
        The oracle accounts for L2 downtimes using Chainlink uptime oracle:
        https://docs.chain.link/data-feeds/l2-sequencer-feeds
@author Curve.Fi
@license MIT
"""
interface Pool:
    def price_oracle(i: uint256 = 0) -> uint256: view  # Universal method!

interface ChainlinkOracle:
    def latestRoundData() -> ChainlinkAnswer: view

struct ChainlinkAnswer:
    roundID: uint80
    answer: int256
    startedAt: uint256
    updatedAt: uint256
    answeredInRound: uint80


POOL: public(immutable(Pool))
BORROWED_IX: public(immutable(uint256))
COLLATERAL_IX: public(immutable(uint256))
N_COINS: public(immutable(uint256))
NO_ARGUMENT: public(immutable(bool))

CHAINLINK_UPTIME_FEED: public(constant(address)) = 0x371EAD81c9102C9BF4874A9075FFFf170F2Ee389
DOWNTIME_WAIT: public(constant(uint256)) = 3988  # 866 * log(100) s


@external
def __init__(
        pool: Pool,
        N: uint256,
        borrowed_ix: uint256,
        collateral_ix: uint256
    ):
    assert borrowed_ix != collateral_ix
    assert borrowed_ix < N
    assert collateral_ix < N
    POOL = pool
    N_COINS = N
    BORROWED_IX = borrowed_ix
    COLLATERAL_IX = collateral_ix

    no_argument: bool = False
    if N == 2:
        success: bool = False
        res: Bytes[32] = empty(Bytes[32])
        success, res = raw_call(
            pool.address,
            _abi_encode(empty(uint256), method_id=method_id("price_oracle(uint256)")),
            max_outsize=32, is_static_call=True, revert_on_failure=False)
        if not success:
            no_argument = True
    NO_ARGUMENT = no_argument


@internal
@view
def _raw_price() -> uint256:
    # Check that we had no downtime
    cl_answer: ChainlinkAnswer = ChainlinkOracle(CHAINLINK_UPTIME_FEED).latestRoundData()
    assert cl_answer.answer == 0, "Sequencer is down"
    assert block.timestamp >= cl_answer.startedAt + DOWNTIME_WAIT, "Wait after downtime"

    p_borrowed: uint256 = 10**18
    p_collateral: uint256 = 10**18

    if NO_ARGUMENT:
        p: uint256 = POOL.price_oracle()
        if COLLATERAL_IX > 0:
            p_collateral = p
        else:
            p_borrowed = p

    else:
        if BORROWED_IX > 0:
            p_borrowed = POOL.price_oracle(BORROWED_IX - 1)
        if COLLATERAL_IX > 0:
            p_collateral = POOL.price_oracle(COLLATERAL_IX - 1)

    return p_collateral * 10**18 / p_borrowed


@external
@view
def price() -> uint256:
    return self._raw_price()


@external
def price_w() -> uint256:
    return self._raw_price()
