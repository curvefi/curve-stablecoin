"""Tests for AggMonetaryPolicy4 rate calculation."""

import boa

from tests.utils.deployers import MOCK_MARKET_DEPLOYER


def test_default_behavior(admin, mock_factory, peg_keepers, mp):
    """A non-zero debt-ratio EMA still affects rate after peg keeper debt goes to zero."""
    borrower = boa.env.generate_address("borrower")

    with boa.env.prank(admin):
        market = MOCK_MARKET_DEPLOYER.deploy()
        mock_factory.add_market(market.address, 10**30)
        mock_factory.set_debt(market.address, 10**24)
        peg_keepers[0].set_debt(5 * 10**22)
        mp.rate_write(market.address)
        peg_keepers[0].set_debt(0)

    assert mp.rate(borrower) < mp.rate0()
