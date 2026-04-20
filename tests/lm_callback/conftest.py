import boa
import pytest
from tests.utils.deployers import (
    ERC20_CRV_DEPLOYER,
    VOTING_ESCROW_DEPLOYER,
    GAUGE_CONTROLLER_DEPLOYER,
    MINTER_DEPLOYER,
    LM_CALLBACK_DEPLOYER,
)
from tests.utils.constants import MAX_UINT256


# ── Market-parameter overrides ─────────────────────────────────────────────────

# We are going to use only Curve LPs with LMCallback
@pytest.fixture(scope="module")
def collateral_decimals():
    return 18


# Borrowed decimals don't matter
@pytest.fixture(scope="module")
def borrowed_decimals():
    return 18


@pytest.fixture(scope="module")
def loan_discount():
    return 5 * 10**16


@pytest.fixture(scope="module")
def liquidation_discount():
    return 2 * 10**16


@pytest.fixture(scope="module")
def min_borrow_rate():
    return 0


@pytest.fixture(scope="module")
def max_borrow_rate():
    return 0


@pytest.fixture(scope="module")
def seed_liquidity(borrowed_token):
    # Large enough to cover the test amounts (e.g. 10**21 * 2600 per user)
    return 10**8 * 10 ** borrowed_token.decimals()


# ── CRV ecosystem ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def crv(admin):
    with boa.env.prank(admin):
        return ERC20_CRV_DEPLOYER.deploy("Curve DAO Token", "CRV", 18)


@pytest.fixture(scope="module")
def voting_escrow(admin, crv):
    with boa.env.prank(admin):
        return VOTING_ESCROW_DEPLOYER.deploy(crv, "Voting-escrowed CRV", "veCRV", "veCRV_0.99")


@pytest.fixture(scope="module")
def gauge_controller(admin, crv, voting_escrow):
    with boa.env.prank(admin):
        gc = GAUGE_CONTROLLER_DEPLOYER.deploy(crv, voting_escrow)
        gc.add_type("crvUSD Market")
        gc.change_type_weight(0, 10**18)
        return gc


@pytest.fixture(scope="module")
def minter(admin, crv, gauge_controller):
    with boa.env.prank(admin):
        _minter = MINTER_DEPLOYER.deploy(crv, gauge_controller)
        crv.set_minter(_minter)
        return _minter


# ── Market aliases ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def lm_factory(controller):
    """Returns the factory whose admin() is used for LMCallback access control."""
    return controller.factory()


# ── Actors ────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def chad(admin, borrowed_token, collateral_token, amm):
    _chad = boa.env.generate_address()
    boa.deal(borrowed_token, _chad, 10**25)
    boa.deal(collateral_token, _chad, 10**25)
    with boa.env.prank(_chad):
        borrowed_token.approve(amm, MAX_UINT256)
        collateral_token.approve(amm, MAX_UINT256)
    return _chad


@pytest.fixture(scope="module", autouse=True)
def setup_approvals(accounts, controller, amm, collateral_token, borrowed_token):
    """Pre-approve tokens for all test accounts so tests don't need inline approvals."""
    for acc in accounts:
        with boa.env.prank(acc):
            collateral_token.approve(amm, MAX_UINT256)
            borrowed_token.approve(amm, MAX_UINT256)
            collateral_token.approve(controller, MAX_UINT256)
            borrowed_token.approve(controller, MAX_UINT256)


# ── LM Callback ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def lm_callback(admin, amm, crv, gauge_controller, minter, controller, lm_factory):
    with boa.env.prank(admin):
        cb = LM_CALLBACK_DEPLOYER.deploy(amm, crv, gauge_controller, minter, lm_factory)
        controller.set_callback(cb)
        gauge_controller.add_gauge(cb.address, 0, 10**18)
        return cb
