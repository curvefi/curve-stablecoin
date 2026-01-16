import boa
import pytest
from tests.utils.constants import ZERO_ADDRESS, WAD


@pytest.fixture(scope="module")
def market_type():
    return "lending"


def test_fee_receiver_flow(
    controller, factory, admin, collateral_token, borrowed_token, amm
):
    """
    Test flow for setting and updating custom fee receivers for Llamalend markets.

    Context:
    This feature allows Llamalend markets to request the DAO for a custom fee receiver.
    This feature has been designed for revenue sharing designs where the custom fee receiver
    would be a helper contract responsible of splitting admin fees between multiple parties.

    Implementation notes:
    - By default all markets have the same fee_receiver (most likely DAO)
    - Markets still fetch the fee receiver from the factory
    - Factory acts as the registry of fee receivers
    - Factory now responds to the fee_receiver getter conditionally depending on the msg.sender
      (since controllers don't specify the first argument, they get the one corresponding to their mapping).
    """
    admin_fee = WAD // 10
    with boa.env.prank(admin):
        controller.set_admin_percentage(admin_fee)

    # Setup
    collateral_amount = 10 ** collateral_token.decimals()
    debt_amount = 500 * 10 ** borrowed_token.decimals()
    bands = 10

    boa.deal(collateral_token, boa.env.eoa, collateral_amount * 10)
    boa.deal(borrowed_token, boa.env.eoa, debt_amount * 10)

    collateral_token.approve(controller, collateral_amount * 10)

    # Create loan
    controller.create_loan(collateral_amount, debt_amount, bands)

    # Time travel to accrue interest
    boa.env.time_travel(seconds=365 * 86400)

    # 1. Check default fee receiver
    default_receiver = factory.default_fee_receiver()
    initial_balance = borrowed_token.balanceOf(default_receiver)

    # Collect fees
    collected = controller.collect_fees()
    assert collected > 0

    assert borrowed_token.balanceOf(default_receiver) == initial_balance + collected

    # 2. Set custom fee receiver
    custom_receiver = boa.env.generate_address("custom_receiver")
    with boa.env.prank(admin):
        factory.set_custom_fee_receiver(controller.address, custom_receiver)

    assert factory.fee_receiver(controller.address) == custom_receiver

    # 3. Generate more fees
    boa.env.time_travel(seconds=365 * 86400)

    initial_balance_custom = borrowed_token.balanceOf(custom_receiver)
    initial_balance_default = borrowed_token.balanceOf(default_receiver)

    # Collect fees
    collected_2 = controller.collect_fees()
    assert collected_2 > 0

    # Verify fees went to custom receiver
    assert (
        borrowed_token.balanceOf(custom_receiver)
        == initial_balance_custom + collected_2
    )
    assert borrowed_token.balanceOf(default_receiver) == initial_balance_default

    # 4. Restore default fee receiver
    with boa.env.prank(admin):
        factory.set_custom_fee_receiver(controller.address, ZERO_ADDRESS)

    assert factory.fee_receiver(controller.address) == default_receiver

    # 5. Generate more fees
    boa.env.time_travel(seconds=365 * 86400)

    initial_balance_custom = borrowed_token.balanceOf(custom_receiver)
    initial_balance_default = borrowed_token.balanceOf(default_receiver)

    # Collect fees
    collected_3 = controller.collect_fees()
    assert collected_3 > 0

    # Verify fees went to default receiver
    assert (
        borrowed_token.balanceOf(default_receiver)
        == initial_balance_default + collected_3
    )
    assert borrowed_token.balanceOf(custom_receiver) == initial_balance_custom
