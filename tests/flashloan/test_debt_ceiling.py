def test_increase_debt_ceiling(controller_factory, flash_lender, stablecoin, max_flash_loan, admin):
    assert stablecoin.balanceOf(flash_lender) == max_flash_loan
    controller_factory.set_debt_ceiling(flash_lender, max_flash_loan * 2, sender=admin)
    assert stablecoin.balanceOf(flash_lender) == max_flash_loan * 2


def test_decrease_debt_ceiling(controller_factory, flash_lender, stablecoin, max_flash_loan, admin):
    assert stablecoin.balanceOf(flash_lender) == max_flash_loan
    controller_factory.set_debt_ceiling(flash_lender, max_flash_loan // 2, sender=admin)
    assert stablecoin.balanceOf(flash_lender) == max_flash_loan // 2


def test_empty_flash_lender(controller_factory, flash_lender, stablecoin, max_flash_loan, admin):
    assert stablecoin.balanceOf(flash_lender) == max_flash_loan
    controller_factory.set_debt_ceiling(flash_lender, 0, sender=admin)
    assert stablecoin.balanceOf(flash_lender) == 0
