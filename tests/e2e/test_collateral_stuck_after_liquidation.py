import boa
import pytest
from tests.utils.protocols import Llamalend
from tests.utils.deployers import ERC20_MOCK_DEPLOYER, DUMMY_PRICE_ORACLE_DEPLOYER
from tests.utils.constants import MAX_UINT256

WAD = 10**18


@pytest.fixture(scope="module")
def market_type():
    """Force lending-only markets for this test."""
    return "lending"


@pytest.fixture(scope="module")
def borrowed_token():
    """Create borrowed token with 6 decimals (like USDC/USDT)."""
    return ERC20_MOCK_DEPLOYER.deploy(6)


@pytest.fixture(scope="module")
def collateral_token():
    """Create collateral token with 18 decimals."""
    return ERC20_MOCK_DEPLOYER.deploy(18)


@pytest.fixture(scope="module")
def price_oracle(admin):
    """Create price oracle with initial price of 3000 * 10**18."""
    initial_price = 3000 * 10**18
    return DUMMY_PRICE_ORACLE_DEPLOYER.deploy(admin, initial_price)


@pytest.fixture(scope="module")
def proto():
    return Llamalend()


@pytest.fixture(scope="module")
def admin(proto):
    return proto.admin


@pytest.fixture(scope="module")
def lending_market(proto, borrowed_token, collateral_token, price_oracle):
    """Create lending market with 6 decimal borrowed token."""
    return proto.create_lending_market(
        borrowed_token=borrowed_token,
        collateral_token=collateral_token,
        A=100,
        fee=10**16,  # 1% fee
        loan_discount=int(0.09 * 10**18),  # 9%
        liquidation_discount=int(0.06 * 10**18),  # 6%
        price_oracle=price_oracle,
        name="Test Vault 6 Decimals",
        min_borrow_rate=10**15 // (365 * 86400),  # 0.1% APR
        max_borrow_rate=10**18 // (365 * 86400),  # 100% APR
        seed_amount=0,  # Don't seed yet, we'll do it manually
    )


@pytest.fixture(scope="module")
def vault(lending_market):
    return lending_market["vault"]


@pytest.fixture(scope="module")
def controller(lending_market, admin):
    ctrl = lending_market["controller"]
    # Set unlimited borrow cap
    with boa.env.prank(admin):
        ctrl.set_borrow_cap(MAX_UINT256)
    return ctrl


@pytest.fixture(scope="module")
def amm(lending_market):
    return lending_market["amm"]


@pytest.fixture(scope="module")
def borrower():
    return boa.env.generate_address("borrower")


@pytest.fixture(scope="module")
def liquidator():
    return boa.env.generate_address("liquidator")


def test_liquidate_full_debt_partial_collateral(
    vault,
    controller,
    amm,
    admin,
    borrowed_token,
    collateral_token,
    price_oracle,
    borrower,
    liquidator,
):
    """
    Demonstrate that liquidating with frac = WAD - 1 can result in:
    - Full debt being repaid (due to rounding up)
    - Only partial collateral being withdrawn
    - User having no debt but collateral still locked in AMM
    """
    borrowed_decimals = borrowed_token.decimals()
    collateral_decimals = collateral_token.decimals()

    # Step 1: Seed vault with a large amount of borrowed tokens
    # Using larger amounts to ensure AMM shares are large enough for dust to remain
    seed_amount = 100_000_000 * 10**borrowed_decimals  # 100M tokens
    with boa.env.prank(admin):
        boa.deal(borrowed_token, admin, seed_amount)
        borrowed_token.approve(vault.address, MAX_UINT256)
        vault.deposit(seed_amount)

    print(f"\n=== Step 1: Seeded vault with {seed_amount} tokens ===")
    print(f"Vault total assets: {vault.totalAssets()}")

    # Step 2: Calculate minimum collateral for a loan with 4 bands
    n_bands = 4  # Minimum number of bands
    # Use a large collateral amount to ensure large share values in AMM
    # This is critical for the vulnerability - with larger shares, the
    # integer division in AMM.withdraw leaves dust when frac < WAD
    test_collateral = 10_000 * 10**collateral_decimals  # 10,000 ETH worth

    max_borrow = controller.max_borrowable(test_collateral, n_bands)
    print(f"\n=== Step 2: Calculate loan parameters ===")
    print(f"With {test_collateral} collateral, max borrow: {max_borrow}")

    # Use min_collateral to get exact minimum collateral for a specific debt
    # Borrow close to max to maximize the effect
    debt_amount = max_borrow * 99 // 100  # Borrow 99% of max
    min_coll = controller.min_collateral(debt_amount, n_bands)
    print(f"Min collateral for {debt_amount} debt: {min_coll}")

    # Use slightly more than min to ensure loan creation succeeds
    collateral_amount = min_coll * 101 // 100  # 1% more than minimum

    # Step 3: Create loan
    with boa.env.prank(borrower):
        boa.deal(collateral_token, borrower, collateral_amount)
        collateral_token.approve(controller.address, MAX_UINT256)
        controller.create_loan(collateral_amount, debt_amount, n_bands)

    print(f"\n=== Step 3: Loan created ===")
    print(f"Collateral deposited: {collateral_amount}")
    print(f"Debt: {controller.debt(borrower)}")
    print(f"Health: {controller.health(borrower, True)}")

    xy = amm.get_sum_xy(borrower)
    print(f"AMM collateral: {xy[1]}")
    print(f"AMM borrowed: {xy[0]}")
    print(f"Loan exists: {controller.loan_exists(borrower)}")

    # Step 4: Drop oracle price to make position liquidatable
    print(f"\n=== Step 4: Dropping oracle price ===")
    current_price = price_oracle.price()
    print(f"Current oracle price: {current_price}")

    # Try dropping by 20% first
    price_drop_pct = 20
    new_price = current_price * (100 - price_drop_pct) // 100

    with boa.env.prank(admin):
        price_oracle.set_price(new_price)

    price_oracle_amm = amm.price_oracle()
    health_after_drop = controller.health(borrower, True)
    print(f"New oracle price: {new_price} ({price_drop_pct}% drop)")
    print(f"New oracle price in AMM: {price_oracle_amm}")
    print(f"Health after drop: {health_after_drop}")

    # If health is still positive, drop more
    while health_after_drop > 0:
        price_drop_pct += 5
        new_price = current_price * (100 - price_drop_pct) // 100
        with boa.env.prank(admin):
            price_oracle.set_price(new_price)
        health_after_drop = controller.health(borrower, True)
        print(
            f"Adjusted price: {new_price / 10**18} ({price_drop_pct}% drop), health: {health_after_drop / 10**18}"
        )

    print(f"Position is now liquidatable (health < 0)")

    # Step 5: Liquidate with WAD - 1 fraction
    print(f"\n=== Step 5: Liquidating with frac = WAD - 1 ===")

    debt_before_liquidation = controller.debt(borrower)
    collateral_before = amm.get_sum_xy(borrower)[1]

    print(f"Debt before liquidation: {debt_before_liquidation}")
    print(f"Collateral before liquidation: {collateral_before}")

    # Calculate how much borrowed token liquidator needs
    tokens_needed = controller.tokens_to_liquidate(borrower, WAD - 1)
    print(f"Tokens needed to liquidate: {tokens_needed}")

    # Give liquidator enough borrowed tokens
    liquidator_amount = debt_before_liquidation + tokens_needed + 10**borrowed_decimals
    with boa.env.prank(liquidator):
        boa.deal(borrowed_token, liquidator, liquidator_amount)
        borrowed_token.approve(controller.address, MAX_UINT256)

    # Liquidate with frac = WAD - 1
    frac = WAD - 1
    with boa.env.prank(liquidator):
        controller.liquidate(borrower, 0, frac)

    # Step 6: Demonstrate the vulnerability
    print(f"\n=== Step 6: Vulnerability Demonstration ===")

    debt_after = controller.debt(borrower)
    xy_after = amm.get_sum_xy(borrower)
    collateral_after = xy_after[1]
    borrowed_after = xy_after[0]
    loan_exists = controller.loan_exists(borrower)
    has_liquidity = amm.has_liquidity(borrower)
    assert debt_after == collateral_after == borrowed_after == 0
    assert not loan_exists
    assert not has_liquidity

    print(f"Debt after liquidation: {debt_after}")
    print(f"Collateral in AMM after (get_sum_xy): {collateral_after}")
    print(f"Borrowed in AMM after (get_sum_xy): {borrowed_after}")
    print(f"Loan exists: {loan_exists}")
    print(f"Has liquidity in AMM: {has_liquidity}")

    # Check raw AMM state - read_user_tick_numbers shows if user has bands
    ns = amm.read_user_tick_numbers(borrower)
    print(f"User tick numbers (n1, n2): {ns}")

    # The vulnerability: debt is 0 but user still has shares/liquidity in AMM
    print(f"\n=== VULNERABILITY CONFIRMED ===")
    print(f"Whole debt repaid: {debt_after == 0}")
    print(f"User still has liquidity in AMM: {has_liquidity}")
    print(f"User removed from loans (loan_exists=False): {not loan_exists}")

    # Demonstrate that user cannot withdraw their remaining collateral
    print(f"\n=== User cannot withdraw remaining collateral ===")
    print(f"Remaining collateral value: {collateral_after}")

    # Try to remove collateral - should fail because loan doesn't exist
    with boa.reverts("Loan doesn't exist"):
        with boa.env.prank(borrower):
            controller.remove_collateral(1, borrower)

    # Try to add collateral - should also fail
    with boa.reverts("Loan doesn't exist"):
        with boa.env.prank(borrower):
            boa.deal(collateral_token, borrower, 10**collateral_decimals)
            collateral_token.approve(controller.address, MAX_UINT256)
            controller.add_collateral(10**collateral_decimals, borrower)

    with boa.env.prank(borrower):
        boa.deal(collateral_token, borrower, collateral_amount)
        debt_amount_adjusted = (
            controller.max_borrowable(collateral_amount, n_bands) * 99 // 100
        )  # we should recalculate due change in price oracle
        controller.create_loan(collateral_amount, debt_amount_adjusted, n_bands)

    # Check the raw collateral amounts by bands (not affected by precision rounding)
    debt_final = controller.debt(borrower)
    xy_final = amm.get_sum_xy(borrower)
    collateral_final = xy_final[1]
    borrowed_final = xy_final[0]
    loan_exists = controller.loan_exists(borrower)
    has_liquidity = amm.has_liquidity(borrower)
    assert debt_final == debt_amount_adjusted
    assert collateral_final == collateral_amount
    assert borrowed_final == 0
    assert loan_exists
    assert has_liquidity
    print(f"Collateral by bands (raw): {xy_final[1]}")
    print(f"Borrowed by bands (raw): {xy_final[0]}")
