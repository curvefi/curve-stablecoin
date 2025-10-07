import boa
import pytest


@pytest.fixture(scope="module")
def seed_liquidity():
    """Default liquidity amount used to seed markets at creation time.
    Override in tests to customize seeding.
    """
    return 0


@pytest.fixture(scope="module")
def deposit(vault, controller, amm, borrowed_token):
    def f(user=boa.env.eoa):
        assets = 100 * 10 ** borrowed_token.decimals()
        boa.deal(borrowed_token, user, assets)
        with boa.env.prank(user):
            borrowed_token.approve(vault, assets)
            vault.deposit(assets)

    return f


def test_max_withdraw_user_balance_limited(
    vault, controller, amm, borrowed_token, deposit
):
    """Test maxWithdraw when user balance is the limiting factor."""
    assert controller.borrowed_balance() == 0
    deposit()
    assert controller.borrowed_balance() > 0

    # maxWithdraw should be limited by user's balance
    user_balance = vault.balanceOf(boa.env.eoa)
    expected_max = vault.convertToAssets(user_balance)
    actual_max = vault.maxWithdraw(boa.env.eoa)
    assert actual_max == expected_max


def test_max_withdraw_controller_limited(
    vault, controller, amm, borrowed_token, deposit
):
    """Test maxWithdraw when controller liquidity is the limiting factor."""
    assert controller.borrowed_balance() == 0
    deposit()

    # Reduce controller balance to be less than user's position
    controller_balance = controller.borrowed_balance()
    assert controller_balance > 0
    # Increase lent to reduce borrowed_balance
    controller.eval(f"self.lent = {controller_balance // 2}")
    limited_balance = controller_balance // 2

    # maxWithdraw should be limited by controller balance
    actual_max = vault.maxWithdraw(boa.env.eoa)
    assert actual_max == limited_balance


def test_max_withdraw_zero_balance(vault, controller, amm, borrowed_token, deposit):
    """Test maxWithdraw when user has no shares."""
    # Load borrowed tokens into vault
    assert controller.borrowed_balance() == 0
    deposit(boa.env.generate_address())
    assert controller.borrowed_balance() > 0

    # User has no shares
    user_balance = vault.balanceOf(boa.env.eoa)
    assert user_balance == 0

    # maxWithdraw should return 0
    actual_max = vault.maxWithdraw(boa.env.eoa)
    assert actual_max == 0


def test_max_withdraw_zero_controller_balance(
    vault, controller, amm, borrowed_token, deposit
):
    """Test maxWithdraw when controller has no liquidity."""
    assert controller.borrowed_balance() == 0
    deposit()

    # Set controller balance to 0 by setting lent = borrowed_balance
    borrowed_balance = controller.borrowed_balance()
    assert borrowed_balance > 0
    controller.eval(f"self.lent = {borrowed_balance}")

    # maxWithdraw should return 0 (limited by controller balance)
    actual_max = vault.maxWithdraw(boa.env.eoa)
    assert actual_max == 0
