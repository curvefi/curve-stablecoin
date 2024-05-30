import boa


def test_params(stablecoin, collateral_token, flash_lender, admin, max_flash_loan):
    assert flash_lender.supportedTokens(stablecoin) is True
    assert flash_lender.supportedTokens(collateral_token) is False

    assert flash_lender.fee() == 0
    assert flash_lender.flashFee(stablecoin, 10**18) == 0
    with boa.reverts('FlashLender: Unsupported currency'):
        flash_lender.flashFee(collateral_token, 10**18)

    assert flash_lender.maxFlashLoan(stablecoin) == stablecoin.balanceOf(flash_lender)
    assert flash_lender.maxFlashLoan(collateral_token) == 0

    assert stablecoin.balanceOf(flash_lender) == max_flash_loan


def test_flashloan(stablecoin, flash_lender, flash_borrower, user, max_flash_loan):
    for i in range(10):
        initial_count = flash_borrower.count()
        initial_total_amount = flash_borrower.total_amount()
        assert initial_count == i
        assert initial_total_amount == i * max_flash_loan
        assert stablecoin.balanceOf(flash_lender) == max_flash_loan
        assert stablecoin.balanceOf(flash_borrower) == 0

        flash_borrower.flashBorrow(stablecoin, max_flash_loan, sender=user)

        count = flash_borrower.count()
        total_amount = flash_borrower.total_amount()
        assert count - initial_count == 1
        assert total_amount - initial_total_amount == max_flash_loan
        assert stablecoin.balanceOf(flash_borrower) == 0
        assert stablecoin.balanceOf(flash_lender) == max_flash_loan


def test_unsupported_currency(collateral_token, flash_borrower, user, max_flash_loan):
    with boa.reverts("FlashLender: Unsupported currency"):
        flash_borrower.flashBorrow(collateral_token, max_flash_loan, sender=user)


def test_too_much_to_lend(stablecoin, flash_borrower, user, max_flash_loan):
    with boa.reverts():
        flash_borrower.flashBorrow(stablecoin, max_flash_loan + 1, sender=user)


def test_callback_failed(stablecoin, flash_borrower, user, max_flash_loan):
    with boa.reverts("FlashLender: Callback failed"):
        flash_borrower.flashBorrow(stablecoin, max_flash_loan, False, sender=user)


def test_repay_not_approved(stablecoin, flash_borrower, user, max_flash_loan):
    with boa.reverts():
        flash_borrower.flashBorrow(stablecoin, max_flash_loan, True, False, sender=user)
