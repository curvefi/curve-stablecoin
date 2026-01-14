import boa

from tests.utils import max_approve
from tests.utils.deployers import ERC20_MOCK_DEPLOYER
from tests.utils.constants import WAD
N_BANDS = 6


def _deploy_lending_market(
    proto,
    price_oracle,
    collateral_token,
    amm_A,
    amm_fee,
    loan_discount,
    liquidation_discount,
    min_borrow_rate,
    max_borrow_rate,
    borrow_decimals: int = 18,
):
    borrowed_token = ERC20_MOCK_DEPLOYER.deploy(borrow_decimals)
    market = proto.create_lending_market(
        borrowed_token=borrowed_token,
        collateral_token=collateral_token,
        A=amm_A,
        fee=amm_fee,
        loan_discount=loan_discount,
        liquidation_discount=liquidation_discount,
        price_oracle=price_oracle,
        name=f"{borrow_decimals}dec Vault",
        min_borrow_rate=min_borrow_rate,
        max_borrow_rate=max_borrow_rate,
        seed_amount=1_000_000 * 10**borrow_decimals,
    )
    controller = market["controller"]
    amm = market["amm"]
    return borrowed_token, controller, amm


def test_liquidate_preview_repro_big_diff_poc(
    proto,
    price_oracle,
    collateral_token,
    borrowed_token,
    amm_A,
    amm_fee,
    loan_discount,
    liquidation_discount,
    min_borrow_rate,
    max_borrow_rate,
):
    """
    POC: reproduce large negative diff (~-7.0e16) from the fuzz sample
    liquidate_preview_fuzz_samples_71929_test_liquidate_preview_fuzz_1767787115.csv
    (collateral=835124687784591872, debt_frac≈0.8351, frac≈0.924, different_liquidator=True).
    """
    collateral = 835124687784591872 // 10**(18 - collateral_token.decimals())
    debt_frac = 835124687784591872  # ~0.8351 WAD
    frac = 923976430962901376  # ~0.924 WAD

    borrowed_token, controller, amm = _deploy_lending_market(
        proto,
        price_oracle,
        collateral_token,
        amm_A,
        amm_fee,
        loan_discount,
        liquidation_discount,
        min_borrow_rate,
        max_borrow_rate,
        borrowed_token.decimals(),
    )
    with boa.env.prank(proto.admin):
        controller.set_borrow_cap(10**30)

    borrower = boa.env.eoa
    liquidator = boa.env.generate_address()

    boa.deal(collateral_token, borrower, collateral)
    max_approve(collateral_token, controller)
    max_approve(borrowed_token, controller)

    max_debt = controller.max_borrowable(collateral, N_BANDS)
    debt = max_debt * debt_frac // WAD
    print(collateral, debt)
    controller.create_loan(collateral, debt, N_BANDS, sender=borrower)

    print("health before price cut", controller.health(borrower, False))

    # single price cut (80% of original) to mirror the fuzz case
    with boa.env.prank(proto.admin):
        price_oracle.set_price(price_oracle.price() // 2)

    print("health after price cut", controller.health(borrower, False))

    health_before = controller.health(borrower, False)
    assert health_before < 0

    tokens_needed = controller.tokens_to_liquidate(borrower, frac, sender=liquidator)
    assert tokens_needed > 0
    boa.deal(borrowed_token, liquidator, tokens_needed + 10)
    max_approve(borrowed_token, controller, sender=liquidator)

    preview = controller.liquidate_health_preview(borrower, liquidator, frac, False)
    print("health_preview", preview)
    controller.liquidate(borrower, 0, frac, sender=liquidator)
    health_after = controller.health(borrower, True)
    print("health_after", health_after)

    assert abs(health_after - preview) <= 1000
