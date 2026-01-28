import boa
from pytest import approx
from tests.utils.deployers import MINT_CONTROLLER_DEPLOYER


LOAN_DISCOUNT = 10 * 10**16
LIQUIDATION_DISCOUNT = 7 * 10**16
DEBT_CEILING = 1000 * 10**18


def test_new_implementations(
    mint_factory,
    controller_blueprint,
    amm_blueprint,
    admin,
    collateral_token,
    crvusd,
    price_oracle,
    monetary_policy,
):
    # --- SET NEW IMPLEMENTATIONS ---

    assert mint_factory.controller_implementation() != controller_blueprint.address
    assert mint_factory.amm_implementation() != amm_blueprint.address

    mint_factory.set_implementations(controller_blueprint, amm_blueprint, sender=admin)

    assert mint_factory.controller_implementation() == controller_blueprint.address
    assert mint_factory.amm_implementation() == amm_blueprint.address

    # --- CREATE A MARKET WITH NEW IMPLEMENTATIONS ---

    controller, amm = mint_factory.add_market(
        collateral_token.address,
        100,
        10**6,
        0,  # admin fee deprecated for mint markets
        price_oracle.address,
        monetary_policy.address,
        LOAN_DISCOUNT,
        LIQUIDATION_DISCOUNT,
        DEBT_CEILING,
        sender=admin,
    )
    controller = MINT_CONTROLLER_DEPLOYER.at(controller)

    assert crvusd.balanceOf(controller) == DEBT_CEILING
    assert mint_factory.debt_ceiling_residual(controller) == DEBT_CEILING

    # --- DECREASE DEBT CEILING ---

    mint_factory.set_debt_ceiling(controller, DEBT_CEILING // 2, sender=admin)

    assert crvusd.balanceOf(controller) == DEBT_CEILING // 2
    assert mint_factory.debt_ceiling_residual(controller) == DEBT_CEILING // 2

    year_in_seconds = 365 * 24 * 3600
    monetary_policy.set_rate(2 * 10**17 // year_in_seconds, sender=admin)

    # --- BORROW ALL ---

    borrower = boa.env.generate_address()
    with boa.env.prank(borrower):
        boa.deal(collateral_token, borrower, 100 * 10**18)
        collateral_token.approve(controller, 2**256 - 1)
        controller.create_loan(10 * 10**18, DEBT_CEILING // 2, 10)
    assert crvusd.balanceOf(controller) == 0
    assert controller.debt(borrower) == DEBT_CEILING // 2
    boa.env.time_travel(year_in_seconds)
    assert controller.debt(borrower) == approx(int(1.2 * DEBT_CEILING) // 2, rel=1e-10)

    # --- COLLECT FEES ABOVE DEBT CEILING ---

    fee_receiver = mint_factory.fee_receiver()

    fee_receiver_balance_before = crvusd.balanceOf(fee_receiver)
    crvusd_total_supply_before = crvusd.totalSupply()

    mint_factory.collect_fees_above_ceiling(controller, sender=admin)

    fee_receiver_balance_after = crvusd.balanceOf(fee_receiver)
    crvusd_total_supply_after = crvusd.totalSupply()

    assert crvusd.balanceOf(controller) == 0
    assert controller.debt(borrower) == mint_factory.debt_ceiling_residual(controller)
    assert (
        fee_receiver_balance_after - fee_receiver_balance_before
        == mint_factory.debt_ceiling_residual(controller) - DEBT_CEILING // 2
    )
    assert (
        crvusd_total_supply_after - crvusd_total_supply_before
        == mint_factory.debt_ceiling_residual(controller) - DEBT_CEILING // 2
    )

    # --- RUG DEBT CEILING ---

    half_debt = controller.debt(borrower) // 2
    mint_factory.set_debt_ceiling(controller, half_debt, sender=admin)
    with boa.env.prank(borrower):
        crvusd.approve(controller, 2**256 - 1)
        controller.repay(int(half_debt * 1.1))

    fee_receiver_balance_before = crvusd.balanceOf(fee_receiver)
    crvusd_total_supply_before = crvusd.totalSupply()

    mint_factory.rug_debt_ceiling(controller)

    crvusd_total_supply_after = crvusd.totalSupply()
    fee_receiver_balance_after = crvusd.balanceOf(fee_receiver)

    assert fee_receiver_balance_after == fee_receiver_balance_before
    assert crvusd_total_supply_before - crvusd_total_supply_after == half_debt
    assert mint_factory.debt_ceiling_residual(controller) == half_debt
    assert controller.debt(borrower) == 2 * half_debt - int(half_debt * 1.1)

    # --- COLLECT FEES ---

    boa.env.time_travel(24 * 3600)

    fee_receiver_balance_before = crvusd.balanceOf(fee_receiver)
    crvusd_total_supply_before = crvusd.totalSupply()

    collected_fees = controller.collect_fees()

    crvusd_total_supply_after = crvusd.totalSupply()
    fee_receiver_balance_after = crvusd.balanceOf(fee_receiver)

    assert collected_fees > 0
    assert fee_receiver_balance_after - fee_receiver_balance_before == collected_fees
    assert crvusd_total_supply_after == crvusd_total_supply_before

    # --- CLOSE THE MARKET ---

    # Set debt_ceiling to 0
    mint_factory.set_debt_ceiling(controller, 0, sender=admin)
    boa.env.time_travel(24 * 3600)

    # Repay full
    boa.deal(crvusd, borrower, DEBT_CEILING)
    controller.repay(2**256 - 1, sender=borrower)
    assert controller.debt(borrower) == 0

    # Rug debt_ceiling
    rug_amount = mint_factory.debt_ceiling_residual(
        controller
    ) - mint_factory.debt_ceiling(controller)

    fee_receiver_balance_before = crvusd.balanceOf(fee_receiver)
    crvusd_total_supply_before = crvusd.totalSupply()

    mint_factory.rug_debt_ceiling(controller)

    crvusd_total_supply_after = crvusd.totalSupply()
    fee_receiver_balance_after = crvusd.balanceOf(fee_receiver)

    assert rug_amount > 0
    assert fee_receiver_balance_after == fee_receiver_balance_before
    assert crvusd_total_supply_before - crvusd_total_supply_after == rug_amount
    assert mint_factory.debt_ceiling_residual(controller) == 0
    assert crvusd.balanceOf(controller) > 0

    # Collect fees
    fee_receiver_balance_before = crvusd.balanceOf(fee_receiver)
    crvusd_total_supply_before = crvusd.totalSupply()

    collected_fees = controller.collect_fees()

    crvusd_total_supply_after = crvusd.totalSupply()
    fee_receiver_balance_after = crvusd.balanceOf(fee_receiver)

    assert collected_fees > 0
    assert fee_receiver_balance_after - fee_receiver_balance_before == collected_fees
    assert crvusd_total_supply_after == crvusd_total_supply_before
    assert crvusd.balanceOf(controller) > 0
