"""
Unit tests for PegKeeperLens — the read-only lens contract over PegKeeperV2.

Coverage
--------
  Constructor invariants  : sanity asserts + echoed immutables
  Orientation             : pegged_price / peg_deviation_bps with the pegged
                            coin at either pool index
  Cooldown                : next_action_eta semantics before and after delay
  Estimate                : every BLOCKER_* code and both ACTION_* directions
  Drift                   : estimate_update().amount matches the actual
                            PegKeeperV2.update() outcome within 1 wei
"""

import boa
import pytest

from tests.utils.deployers import (
    PEG_KEEPER_LENS_DEPLOYER,
    PEG_KEEPER_V2_DEPLOYER,
    ERC20_MOCK_DEPLOYER,
)


ONE = 10**18
BPS = 10_000

# Action codes — mirror PegKeeperLens.
A_NOOP = 0
A_PROVIDE = 1
A_WITHDRAW = 2

# Blocker codes — mirror PegKeeperLens.
B_READY = 0
B_COOLDOWN = 1
B_REGULATOR = 2
B_BALANCED = 3
B_UNPROFITABLE = 4


# --------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------

@pytest.fixture(scope="module")
def lens_old(peg_keepers):
    """Lens over peg_keepers[0]: pre-NG StableSwap, 6-dec other coin (PEG_MUL = 10**12)."""
    return PEG_KEEPER_LENS_DEPLOYER.deploy(peg_keepers[0])


@pytest.fixture(scope="module")
def lens_ng(peg_keepers):
    """Lens over peg_keepers[1]: StableSwap-NG, 18-dec other coin (PEG_MUL = 1)."""
    return PEG_KEEPER_LENS_DEPLOYER.deploy(peg_keepers[1])


@pytest.fixture(scope="module")
def lens(lens_ng):
    """Default lens for tests that do not care about pool dialect."""
    return lens_ng


# --------------------------------------------------------------------
# Constructor
# --------------------------------------------------------------------

class TestConstructor:
    def test_records_keeper_and_pool(self, lens_ng, peg_keepers, stableswap_b):
        """Lens echoes the keeper and pool addresses it was deployed against."""
        assert lens_ng.PEG_KEEPER() == peg_keepers[1].address
        assert lens_ng.POOL() == stableswap_b.address

    def test_records_pegged_and_regulator(self, lens_ng, peg_keepers, stablecoin, reg):
        """Pegged token and regulator come from the keeper, not from the deployer."""
        assert lens_ng.PEGGED() == stablecoin.address
        assert lens_ng.REGULATOR() == reg.address

    def test_records_orientation(self, lens_ng, peg_keepers):
        """I and I_OTHER agree with PegKeeperV2's IS_INVERSE."""
        is_inverse = peg_keepers[1].IS_INVERSE()
        expected_i = 0 if is_inverse else 1
        assert lens_ng.I() == expected_i
        assert lens_ng.I_OTHER() == 1 - expected_i

    def test_records_peg_mul_for_six_decimal_pair(self, lens_old):
        """PEG_MUL scales the 6-dec other coin's balance up to 18 dec."""
        assert lens_old.PEG_MUL() == 10**12

    def test_records_peg_mul_for_eighteen_decimal_pair(self, lens_ng):
        """PEG_MUL is 1 when both pool coins are already 18-dec."""
        assert lens_ng.PEG_MUL() == 1

    def test_records_is_ng_flag(self, lens_old, lens_ng):
        """IS_NG is snapshotted from the keeper so the oracle view branches correctly."""
        assert lens_old.IS_NG() is False
        assert lens_ng.IS_NG() is True

    def test_reverts_when_pegged_index_mismatches_pool(self, peg_keepers):
        """
        Sanity assert in the constructor catches a (keeper, pool) pair where
        the keeper's `pegged()` is not the address at the implied index in the
        pool. A real PegKeeperV2 always agrees with its pool by construction;
        we forge the disagreement by deploying a stub keeper whose pegged()
        returns a token the pool does not list. This guards against deploying
        the lens against the wrong keeper or pool by mistake.
        """
        keeper = peg_keepers[1]
        rogue = ERC20_MOCK_DEPLOYER.deploy(18)
        stub = boa.loads(
            f"""
# pragma version 0.4.3

POOL: immutable(address)
PEGGED_: immutable(address)
REG: immutable(address)

@deploy
def __init__():
    POOL = {keeper.pool()}
    PEGGED_ = {rogue.address}
    REG = {keeper.regulator()}

@view
@external
def pool() -> address:
    return POOL

@view
@external
def pegged() -> address:
    return PEGGED_

@view
@external
def regulator() -> address:
    return REG

@view
@external
def IS_INVERSE() -> bool:
    return False

@view
@external
def IS_NG() -> bool:
    return True
"""
        )
        with boa.reverts("Lens: pegged index mismatch"):
            PEG_KEEPER_LENS_DEPLOYER.deploy(stub)


# --------------------------------------------------------------------
# Orientation
# --------------------------------------------------------------------

class TestOrientation:
    def test_pegged_price_returns_raw_oracle_when_pegged_is_coin_one(
        self, lens_ng, stableswap_b
    ):
        """With pegged at index 1, the lens passes price_oracle(0) through unchanged."""
        raw = stableswap_b.price_oracle(0)
        assert lens_ng.pegged_price() == raw

    def test_pegged_price_inverts_when_pegged_is_coin_zero(
        self, swap_deployer, swap_impl_ng, stablecoin, stablecoin_b,
        controller_factory, reg, admin,
    ):
        """
        With pegged at index 0, the lens returns 1e36 / raw to keep the
        returned value as "1 PEGGED in OTHER", matching the regulator's
        _get_price_oracle convention.
        """
        with boa.env.prank(admin):
            inverted_addr = swap_deployer.deploy_ng(stablecoin, stablecoin_b)
            inverted = swap_impl_ng.deployer.at(inverted_addr)
            keeper = PEG_KEEPER_V2_DEPLOYER.deploy(
                inverted.address, 2 * 10**4,
                controller_factory.address, reg.address, admin,
            )
        assert keeper.IS_INVERSE() is True
        lens = PEG_KEEPER_LENS_DEPLOYER.deploy(keeper)
        raw = inverted.price_oracle(0)
        assert lens.pegged_price() == ONE * ONE // raw

    def test_peg_deviation_bps_matches_oriented_oracle(self, lens_ng, stableswap_b):
        """
        peg_deviation_bps follows the oriented oracle's distance from 1e18.
        We assert against the live oracle rather than synthesised values to
        avoid coupling the test to StableSwap-NG's internal EMA storage layout.
        """
        raw = stableswap_b.price_oracle(0)
        if raw >= ONE:
            expected = (raw - ONE) * BPS // ONE
        else:
            expected = (ONE - raw) * BPS // ONE
        assert lens_ng.peg_deviation_bps() == expected


# --------------------------------------------------------------------
# Cooldown
# --------------------------------------------------------------------

class TestCooldown:
    def test_eta_clamps_to_now_when_cooldown_already_elapsed(self, lens_ng):
        """A keeper that has never acted has last_change=0; eta clamps to now."""
        assert lens_ng.next_action_eta() == boa.env.evm.patch.timestamp

    def test_eta_advances_after_update(
        self, lens_ng, peg_keepers, provide_token_to_peg_keepers_no_sleep
    ):
        """
        provide_token_to_peg_keepers_no_sleep calls update() without time-travel,
        so last_change == now and eta = now + action_delay > now.
        """
        eta = lens_ng.next_action_eta()
        keeper = peg_keepers[1]
        expected = keeper.last_change() + keeper.action_delay()
        assert eta == expected
        assert eta > boa.env.evm.patch.timestamp


# --------------------------------------------------------------------
# Estimate
# --------------------------------------------------------------------

class TestEstimate:
    def test_blocker_cooldown_when_action_delay_not_elapsed(
        self, lens_ng, provide_token_to_peg_keepers_no_sleep
    ):
        """After update() and before action_delay elapses, blocker == COOLDOWN."""
        preview = lens_ng.estimate_update()
        assert preview.blocker == B_COOLDOWN
        assert preview.action == A_NOOP
        assert preview.amount == 0
        assert preview.caller_profit == 0

    def test_blocker_balanced_when_pool_exactly_at_par(
        self, lens_ng, provide_token_to_peg_keepers
    ):
        """
        provide_token_to_peg_keepers re-balances the pool to par after seeding
        peg_keeper debt and time-travels past the cooldown. Estimate must report
        BLOCKER_BALANCED, not READY.
        """
        preview = lens_ng.estimate_update()
        assert preview.blocker == B_BALANCED
        assert preview.action == A_NOOP
        assert preview.amount == 0

    def test_blocker_regulator_when_provide_allowed_is_zero(
        self, lens_ng, peg_keepers, reg, stableswap_b, admin, imbalance_pool
    ):
        """
        Imbalance the pool so update() would take the provide branch, then
        kill provide on the regulator. The lens must report BLOCKER_REGULATOR
        with ACTION_PROVIDE preserved (so monitors see which path was banned).
        """
        boa.env.time_travel(seconds=peg_keepers[1].action_delay() + 1)
        # Add the non-pegged coin to push pegged into scarcity (provide branch).
        imbalance_pool(stableswap_b, 0)
        with boa.env.prank(admin):
            reg.set_killed(1)  # Killed.Provide
        try:
            preview = lens_ng.estimate_update()
            assert preview.blocker == B_REGULATOR
            assert preview.action == A_PROVIDE
            assert preview.amount == 0
        finally:
            with boa.env.prank(admin):
                reg.set_killed(0)

    def test_provide_direction_when_pegged_scarce(
        self, lens_ng, peg_keepers, stableswap_b, imbalance_pool,
    ):
        """When the non-pegged coin oversupplies the pool, update() provides."""
        boa.env.time_travel(seconds=peg_keepers[1].action_delay() + 1)
        imbalance_pool(stableswap_b, 0)
        preview = lens_ng.estimate_update()
        assert preview.action == A_PROVIDE
        assert preview.amount > 0
        assert preview.blocker in (B_READY, B_UNPROFITABLE)

    def test_withdraw_direction_when_pegged_abundant(
        self, lens_ng, peg_keepers, stableswap_b, imbalance_pool,
        provide_token_to_peg_keepers,
    ):
        """When the pegged coin oversupplies the pool, update() withdraws."""
        boa.env.time_travel(seconds=peg_keepers[1].action_delay() + 1)
        imbalance_pool(stableswap_b, 1)
        preview = lens_ng.estimate_update()
        assert preview.action == A_WITHDRAW
        assert preview.amount > 0

    def test_update_blocker_scalar_equals_struct_field(
        self, lens_ng, provide_token_to_peg_keepers_no_sleep
    ):
        """update_blocker() must agree with estimate_update().blocker bit-for-bit."""
        assert lens_ng.update_blocker() == lens_ng.estimate_update().blocker


# --------------------------------------------------------------------
# Drift — the test that earns trust
# --------------------------------------------------------------------

class TestDrift:
    def test_estimate_amount_matches_actual_update_within_one_wei(
        self, lens_ng, peg_keepers, stableswap_b, imbalance_pool,
        peg_keeper_updater,
    ):
        """
        With the pool imbalanced and cooldown elapsed, the amount predicted by
        the lens must match the change in PegKeeperV2.debt() after update()
        within 1 wei. This is the load-bearing guarantee a keeper or dashboard
        reads.
        """
        keeper = peg_keepers[1]
        boa.env.time_travel(seconds=keeper.action_delay() + 1)
        imbalance_pool(stableswap_b, 0)  # provide direction

        preview = lens_ng.estimate_update()
        assert preview.action == A_PROVIDE
        assert preview.amount > 0

        debt_before = keeper.debt()
        with boa.env.prank(peg_keeper_updater):
            keeper.update()
        debt_after = keeper.debt()

        actual = debt_after - debt_before
        assert abs(int(actual) - int(preview.amount)) <= 1, (
            f"Drift: lens predicted {preview.amount}, "
            f"keeper moved {actual} ({int(actual) - int(preview.amount):+d} wei)"
        )

    def test_estimate_amount_matches_actual_withdraw_within_one_wei(
        self, lens_ng, peg_keepers, stableswap_b, imbalance_pool,
        provide_token_to_peg_keepers, peg_keeper_updater,
    ):
        """Same drift guarantee on the withdraw branch."""
        keeper = peg_keepers[1]
        boa.env.time_travel(seconds=keeper.action_delay() + 1)
        imbalance_pool(stableswap_b, 1)  # withdraw direction

        preview = lens_ng.estimate_update()
        assert preview.action == A_WITHDRAW
        assert preview.amount > 0

        debt_before = keeper.debt()
        with boa.env.prank(peg_keeper_updater):
            keeper.update()
        debt_after = keeper.debt()

        actual = debt_before - debt_after
        assert abs(int(actual) - int(preview.amount)) <= 1, (
            f"Drift: lens predicted {preview.amount}, "
            f"keeper moved {actual} ({int(actual) - int(preview.amount):+d} wei)"
        )
