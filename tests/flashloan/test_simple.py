def test_simple(flash_lender, stablecoin, admin):
    assert flash_lender.supportedTokens(stablecoin.address) is True
    assert stablecoin.balanceOf(flash_lender) == 3 * 10**6 * 10**18
