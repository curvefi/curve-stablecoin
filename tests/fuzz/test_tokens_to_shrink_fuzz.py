import boa
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from tests.utils.constants import MIN_TICKS, WAD, ZERO_ADDRESS


@pytest.fixture(scope="module")
def seed_liquidity():
    """Default liquidity amount used to seed markets at creation time.
    Override in tests to customize seeding.
    """
    return 5000 * 10**22


@given(
    N=st.integers(min_value=4, max_value=50),
    collateral_amount=st.integers(min_value=10**12, max_value=10**22),
    p_o_frac=st.integers(min_value=0, max_value=WAD),
    trade_frac=st.integers(min_value=10**15, max_value=WAD),
)
@settings(max_examples=5000)
def test_tokens_to_shrink(
    price_oracle,
    controller,
    amm,
    collateral_token,
    borrowed_token,
    admin,
    N,
    collateral_amount,
    p_o_frac,
    trade_frac,
):
    collateral_token.approve(controller, 2**256 - 1)
    borrowed_token.approve(controller, 2**256 - 1)
    collateral_token.approve(amm, 2**256 - 1)
    borrowed_token.approve(amm, 2**256 - 1)

    # --- Initial deposit ---

    debt = controller.max_borrowable(collateral_amount, N)
    boa.deal(collateral_token, boa.env.eoa, collateral_amount)
    controller.create_loan(collateral_amount, debt, N)

    # --- Change oracle price ---

    n1, n2 = amm.read_user_tick_numbers(boa.env.eoa)
    p_up, p_down = amm.p_oracle_up(n1 - 2), amm.p_oracle_down(n2 + 2)
    oracle_price = p_down + (p_up - p_down) * p_o_frac // WAD
    oracle_price_band = n1 - 2
    while amm.p_oracle_down(oracle_price_band) > oracle_price:
        oracle_price_band += 1

    with boa.env.prank(admin):
        price_oracle.set_price(oracle_price)
        boa.env.time_travel(3600)
        assert amm.price_oracle() == oracle_price

    # --- Trade to push user into soft-liquidation ---

    trade_amount = debt * trade_frac // WAD
    boa.deal(borrowed_token, boa.env.eoa, trade_amount)
    amm.exchange(0, 1, trade_amount, 0)
    user_state = controller.user_state(boa.env.eoa)
    active_band = amm.active_band()

    # --- Repay ---

    if n2 < active_band + MIN_TICKS:
        with boa.reverts("Can't shrink"):
            controller.tokens_to_shrink(boa.env.eoa)
    else:
        tokens_to_shrink = controller.tokens_to_shrink(boa.env.eoa)

        boa.deal(borrowed_token, boa.env.eoa, tokens_to_shrink)
        controller.repay(
            tokens_to_shrink, boa.env.eoa, active_band, ZERO_ADDRESS, b"", True
        )

        _n1, _n2 = amm.read_user_tick_numbers(boa.env.eoa)

        if tokens_to_shrink > 0:
            assert (
                max(active_band, oracle_price_band) + 1
                <= _n1
                <= max(active_band, oracle_price_band) + 2
            )
        else:
            assert _n1 > active_band
        assert amm.active_band() == active_band
        assert _n2 - _n1 == n2 - (active_band + 1)

        _user_state = controller.user_state(boa.env.eoa)
        assert _user_state[0] == user_state[0]  # collateral unchanged
        assert _user_state[1] == 0  # borrowed == 0
        assert (
            _user_state[2] == user_state[2] - user_state[1] - tokens_to_shrink
        )  # _debt == debt - xy[0] - tokens_to_shrink
        assert _user_state[3] == min(n2 - active_band, n2 - n1 + 1)
