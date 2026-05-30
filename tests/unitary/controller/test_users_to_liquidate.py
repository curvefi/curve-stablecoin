import boa
import pytest
from tests.utils import max_approve

N_BANDS = 6
DYNARRAY_LIMIT = 1000


@pytest.fixture(scope="module")
def seed_liquidity(borrowed_token):
    return 1000 * 18**6 * 10**borrowed_token.decimals()


def test_users_to_liquidate_overflow(
    controller,
    collateral_token,
    price_oracle,
    admin,
):
    """
    users_with_health accumulates results into a DynArray[Position, 1000] and
    appends unconditionally whenever a position falls below the health threshold,
    without checking remaining capacity. When more than 1000 positions are
    unhealthy in a single scan, Vyper raises a DynArray overflow revert on the
    1001st append.

    users_to_liquidate() with default _limit=0 expands to n_loans and scans the
    entire loan book. Liquidation bots relying on the default arguments will
    encounter a revert and be unable to retrieve the liquidation list during a
    market-wide crash. The inner loop should break once the output array is full.
    """
    collateral_amount = int(0.1 * 10 ** collateral_token.decimals())
    n_overflow = DYNARRAY_LIMIT + 1

    # ================= Create n_overflow max-borrow loans =================

    for _ in range(n_overflow):
        borrower = boa.env.generate_address()
        boa.deal(collateral_token, borrower, collateral_amount)
        with boa.env.prank(borrower):
            max_approve(collateral_token, controller)
            debt = controller.max_borrowable(collateral_amount, N_BANDS)
            controller.create_loan(collateral_amount, debt, N_BANDS)

    assert controller.n_loans() == n_overflow

    # ================= Crash oracle to push all positions below health 0 =================

    price_oracle.set_price(price_oracle.price() // 2, sender=admin)
    assert controller.health(controller.loans(0), True) < 0

    # ================= Paginated call succeeds =================

    # Scanning exactly DYNARRAY_LIMIT loans can produce at most DYNARRAY_LIMIT
    # results, so no overflow is possible.
    paginated = controller.users_to_liquidate(0, DYNARRAY_LIMIT)
    assert len(paginated) == DYNARRAY_LIMIT

    # ================= Default call should not revert =================

    # users_to_liquidate() expands _limit=0 to n_loans (1001), finds all 1001
    # positions unhealthy, and tries to append a 1001st element to the
    # DynArray[Position, 1000]. The loop should break when the array is full
    # and return up to 1000 results instead of reverting.
    result = controller.users_to_liquidate()
    assert len(result) == DYNARRAY_LIMIT
