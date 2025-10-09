import boa
import pytest


@pytest.fixture(scope="module")
def seed_liquidity():
    """Default liquidity amount used to seed markets at creation time.
    Override in tests to customize seeding.
    """
    return 0


def test_max_redeem_user_balance_limited(
    vault, controller, amm, borrowed_token, deposit_into_vault
):
    """Test maxRedeem when user balance is the limiting factor."""
    deposit_into_vault()

    # maxRedeem should be limited by user's balance
    user_balance = vault.balanceOf(boa.env.eoa)
    expected_max = user_balance
    actual_max = vault.maxRedeem(boa.env.eoa)
    assert actual_max == expected_max


def test_max_redeem_controller_limited(
    vault, controller, amm, borrowed_token, deposit_into_vault
):
    """Test maxRedeem when controller liquidity is the limiting factor."""
    deposit_into_vault()

    # Reduce controller balance to be less than user's position
    controller_balance = controller.borrowed_balance()
    # Increase lent to reduce borrowed_balance
    controller.eval(f"self.lent = {controller_balance // 2}")
    limited_balance = controller_balance // 2

    # maxRedeem should be limited by controller balance
    expected_max = vault.eval(f"self._convert_to_shares({limited_balance}, False)")
    actual_max = vault.maxRedeem(boa.env.eoa)
    assert actual_max == expected_max


def test_max_redeem_zero_balance(
    vault, controller, amm, borrowed_token, deposit_into_vault
):
    """Test maxRedeem when user has no shares."""
    # Load borrowed tokens into vault
    deposit_into_vault(user=boa.env.generate_address())

    # User has no shares
    user_balance = vault.balanceOf(boa.env.eoa)
    assert user_balance == 0

    # maxRedeem should return 0
    actual_max = vault.maxRedeem(boa.env.eoa)
    assert actual_max == 0


def test_max_redeem_zero_controller_balance(
    vault, controller, amm, borrowed_token, deposit_into_vault
):
    """Test maxRedeem when controller has no liquidity."""
    deposit_into_vault()

    # Set controller balance to 0 by setting lent = borrowed_balance
    borrowed_balance = controller.borrowed_balance()
    controller.eval(f"self.lent = {borrowed_balance}")

    # maxRedeem should return 0 (limited by controller balance)
    actual_max = vault.maxRedeem(boa.env.eoa)
    assert actual_max == 0
