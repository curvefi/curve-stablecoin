import boa


def test_increase_debt_ceiling(controller_factory, flash_lender, stablecoin, max_flash_loan, admin):
    assert controller_factory.debt_ceiling_residual(flash_lender) == max_flash_loan
    assert stablecoin.balanceOf(flash_lender) == max_flash_loan

    controller_factory.set_debt_ceiling(flash_lender, max_flash_loan * 2, sender=admin)

    assert controller_factory.debt_ceiling_residual(flash_lender) == max_flash_loan * 2
    assert stablecoin.balanceOf(flash_lender) == max_flash_loan * 2


def test_decrease_debt_ceiling(controller_factory, flash_lender, stablecoin, max_flash_loan, admin):
    assert controller_factory.debt_ceiling_residual(flash_lender) == max_flash_loan
    assert stablecoin.balanceOf(flash_lender) == max_flash_loan

    controller_factory.set_debt_ceiling(flash_lender, max_flash_loan // 2, sender=admin)

    assert controller_factory.debt_ceiling_residual(flash_lender) == max_flash_loan // 2
    assert stablecoin.balanceOf(flash_lender) == max_flash_loan // 2


def test_empty_flash_lender(controller_factory, flash_lender, stablecoin, max_flash_loan, admin):
    assert controller_factory.debt_ceiling_residual(flash_lender) == max_flash_loan
    assert stablecoin.balanceOf(flash_lender) == max_flash_loan

    controller_factory.set_debt_ceiling(flash_lender, 0, sender=admin)

    assert controller_factory.debt_ceiling_residual(flash_lender) == 0
    assert stablecoin.balanceOf(flash_lender) == 0


def test_increase_debt_ceiling_with_excess(controller_factory, flash_lender, stablecoin, max_flash_loan, admin):
    with boa.env.prank(admin):
        stablecoin.transfer(flash_lender, 10**21)

        assert controller_factory.debt_ceiling_residual(flash_lender) == max_flash_loan
        assert stablecoin.balanceOf(flash_lender) == max_flash_loan + 10**21

        controller_factory.set_debt_ceiling(flash_lender, max_flash_loan * 2)

        assert controller_factory.debt_ceiling_residual(flash_lender) == max_flash_loan * 2
        assert stablecoin.balanceOf(flash_lender) == max_flash_loan * 2 + 10**21


def test_decrease_debt_ceiling_with_excess(controller_factory, flash_lender, stablecoin, max_flash_loan, admin):
    with boa.env.prank(admin):
        stablecoin.transfer(flash_lender, 10**21)

        assert controller_factory.debt_ceiling_residual(flash_lender) == max_flash_loan
        assert stablecoin.balanceOf(flash_lender) == max_flash_loan + 10**21

        controller_factory.set_debt_ceiling(flash_lender, max_flash_loan // 2, sender=admin)

        assert controller_factory.debt_ceiling_residual(flash_lender) == max_flash_loan // 2
        assert stablecoin.balanceOf(flash_lender) == max_flash_loan // 2 + 10**21


def test_empty_flash_lender_with_excess(controller_factory, flash_lender, stablecoin, max_flash_loan, admin):
    with boa.env.prank(admin):
        stablecoin.transfer(flash_lender, 10**21)

        assert controller_factory.debt_ceiling_residual(flash_lender) == max_flash_loan
        assert stablecoin.balanceOf(flash_lender) == max_flash_loan + 10**21

        controller_factory.set_debt_ceiling(flash_lender, 0, sender=admin)

        assert controller_factory.debt_ceiling_residual(flash_lender) == 0
        assert stablecoin.balanceOf(flash_lender) == 10**21
