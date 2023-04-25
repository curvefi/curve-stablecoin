import boa
import pytest
from collections import defaultdict
from ..conftest import approx


@pytest.fixture(scope="module")
def lm_callback(market_amm, market_controller, admin):
    with boa.env.prank(admin):
        cb = boa.load('contracts/testing/DummyLMCallback.vy', market_amm.address)
        market_controller.set_callback(cb.address)
        return cb


def test_lm_callback(collateral_token, lm_callback, market_amm, market_controller, accounts):
    """
    This unitary test doesn't do trades etc - that has to be done in a full stateful test
    """
    amount = 10 * 10**18
    debt = 5 * 10**18 * 3000
    for i, acc in enumerate(accounts[:10]):
        with boa.env.prank(acc):
            collateral_token._mint_for_testing(acc, amount)
            market_controller.create_loan(amount, debt, 5 + i)

    user_amounts = defaultdict(int)
    for n in range(market_amm.min_band(), market_amm.max_band() + 1):
        cps = lm_callback._debug_collateral_per_share(n)
        for acc in accounts[:10]:
            us = lm_callback._debug_user_shares(acc, n)
            user_amounts[acc] += cps * us // 10**18

    for acc in accounts[:10]:
        assert approx(user_amounts[acc], market_amm.get_sum_xy(acc)[1], 1e-5)
