import boa
import pytest


@pytest.fixture(scope="module")
def seed_liquidity():
    """Default liquidity amount used to seed markets at creation time.
    Override in tests to customize seeding.
    """
    return 0


def test_max_withdraw_user_balance_limited(
    vault, controller, amm, borrowed_token, deposit_into_vault
):
    """Test maxWithdraw when user balance is the limiting factor."""
    deposit_into_vault()

    # maxWithdraw should be limited by user's balance
    user_balance = vault.balanceOf(boa.env.eoa)
    expected_max = vault.convertToAssets(user_balance)
    actual_max = vault.maxWithdraw(boa.env.eoa)
    assert actual_max == expected_max


def test_max_withdraw_controller_limited(
    vault, controller, amm, borrowed_token, deposit_into_vault
):
    """Test maxWithdraw when controller liquidity is the limiting factor."""
    deposit_into_vault()

    # Reduce controller balance to be less than user's position
    controller_balance = controller.borrowed_balance()
    # Increase lent to reduce borrowed_balance
    controller.eval(f"core.lent = {controller_balance // 2}")
    limited_balance = controller_balance // 2

    # maxWithdraw should be limited by controller balance
    actual_max = vault.maxWithdraw(boa.env.eoa)
    assert actual_max == limited_balance


def test_max_withdraw_zero_balance(
    vault, controller, amm, borrowed_token, deposit_into_vault
):
    """Test maxWithdraw when user has no shares."""
    # Load borrowed tokens into vault
    deposit_into_vault(boa.env.generate_address())

    # User has no shares
    user_balance = vault.balanceOf(boa.env.eoa)
    assert user_balance == 0

    # maxWithdraw should return 0
    actual_max = vault.maxWithdraw(boa.env.eoa)
    assert actual_max == 0


def test_max_withdraw_zero_controller_balance(
    vault, controller, amm, borrowed_token, deposit_into_vault
):
    """Test maxWithdraw when controller has no liquidity."""
    deposit_into_vault()

    # Set controller balance to 0 by setting lent = borrowed_balance
    controller.eval(f"core.lent = {controller.borrowed_balance()}")

    # maxWithdraw should return 0 (limited by controller balance)
    actual_max = vault.maxWithdraw(boa.env.eoa)
    assert actual_max == 0
