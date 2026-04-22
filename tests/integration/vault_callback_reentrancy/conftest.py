import boa
import pytest

from tests.utils import max_approve
from tests.utils.constants import MAX_UINT256
from tests.utils.deployers import VAULT_REENTRANCY_CALLBACK_DEPLOYER


N = 10

# ---------------------------------------------------------------------------
# Action constants – mirror VaultReentrancyCallback.vy
# ---------------------------------------------------------------------------
ACTION_DEPOSIT = 0
ACTION_MINT = 1
ACTION_WITHDRAW = 2
ACTION_REDEEM = 3
ACTION_RECORD = 4

VAULT_OPS = [ACTION_DEPOSIT, ACTION_MINT, ACTION_WITHDRAW, ACTION_REDEEM]

# ---------------------------------------------------------------------------
# Market fixtures – lending only (mint markets have no vault)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def market_type():
    return "lending"


@pytest.fixture(scope="module")
def borrowed_decimals():
    return 18


@pytest.fixture(scope="module")
def collateral_decimals():
    return 18


@pytest.fixture(scope="module")
def borrow_cap():
    return MAX_UINT256


# ---------------------------------------------------------------------------
# Shared callback contract
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cb(vault, borrowed_token, collateral_token):
    return VAULT_REENTRANCY_CALLBACK_DEPLOYER.deploy(
        vault.address, borrowed_token.address, collateral_token.address
    )


# ---------------------------------------------------------------------------
# Helpers (plain functions, not fixtures)
# ---------------------------------------------------------------------------


def snapshot(vault):
    return {
        "pps": vault.pricePerShare(),
        "convert_to_assets": vault.convertToAssets(10**18),
        "convert_to_shares": vault.convertToShares(10**18),
    }


def assert_stable(before, cb_contract, after):
    assert before["pps"] == cb_contract.pps_during() == after["pps"]
    assert (
        before["convert_to_assets"]
        == cb_contract.convert_to_assets_during()
        == after["convert_to_assets"]
    )
    assert (
        before["convert_to_shares"]
        == cb_contract.convert_to_shares_during()
        == after["convert_to_shares"]
    )


def open_max_loan(controller, collateral_token, debt, n_ticks):
    """Create a fresh loan and return borrower."""
    borrower = boa.env.generate_address()
    collateral = controller.min_collateral(debt, n_ticks)
    boa.deal(collateral_token, borrower, collateral)
    with boa.env.prank(borrower):
        max_approve(collateral_token, controller)
        controller.create_loan(collateral, debt, n_ticks)
    return borrower


def seed_shares(cb_contract, borrowed_token, amount):
    """Pre-fund cb with vault shares for WITHDRAW/REDEEM reentrancy tests."""
    boa.deal(borrowed_token, cb_contract.address, amount)
    cb_contract.seed_vault_shares(amount)


def seed_borrowed(cb_contract, borrowed_token, amount):
    """Pre-fund cb with borrowed tokens for DEPOSIT/MINT reentrancy tests."""
    boa.deal(borrowed_token, cb_contract.address, amount)


def setup_caller(controller, borrower, different_caller):
    """Return borrower if different_caller is False, otherwise generate a new
    address, grant it controller.approve, and return it."""
    if not different_caller:
        return borrower
    else:
        caller = boa.env.generate_address()
        controller.approve(caller, True, sender=borrower)
        return caller
