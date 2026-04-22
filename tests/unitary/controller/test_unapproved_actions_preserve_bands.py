import boa
import pytest

from tests.utils import max_approve

N_BANDS = 6


def _position_snapshot(controller, amm, borrower):
    return {
        "ticks": tuple(amm.read_user_tick_numbers(borrower)),
        "state": tuple(controller.user_state(borrower)),
        "xy": tuple(amm.get_sum_xy(borrower)),
        "has_liquidity": amm.has_liquidity(borrower),
    }


def _assert_position_unchanged(controller, amm, borrower, before):
    after = _position_snapshot(controller, amm, borrower)
    assert after == before


@pytest.fixture(scope="function")
def create_loan(controller, collateral_token, borrowed_token):
    def fn(debt_ratio_numerator=9, debt_ratio_denominator=10):
        borrower = boa.env.eoa
        collateral_amount = int(0.1 * 10 ** collateral_token.decimals())
        max_debt = controller.max_borrowable(collateral_amount, N_BANDS)
        assert max_debt > 0

        debt_amount = max_debt * debt_ratio_numerator // debt_ratio_denominator
        debt_amount = max(debt_amount, 1)

        boa.deal(collateral_token, borrower, collateral_amount)
        max_approve(collateral_token, controller, sender=borrower)
        max_approve(borrowed_token, controller, sender=borrower)
        controller.create_loan(collateral_amount, debt_amount, N_BANDS, sender=borrower)

        return borrower, collateral_amount, debt_amount

    return fn


def test_unapproved_controller_and_amm_actions_preserve_user_bands(
    controller,
    amm,
    borrowed_token,
    collateral_token,
    create_loan,
):
    borrower, collateral_amount, debt_amount = create_loan()
    attacker = boa.env.generate_address("attacker")

    assert controller.health(borrower) > 0

    add_collateral = max(collateral_amount // 10, 1)
    more_debt = max(debt_amount // 10, 1)
    repay_amount = max(debt_amount // 10, 1)

    boa.deal(collateral_token, attacker, collateral_amount)
    boa.deal(borrowed_token, attacker, debt_amount)
    max_approve(collateral_token, controller, sender=attacker)
    max_approve(borrowed_token, controller, sender=attacker)

    before = _position_snapshot(controller, amm, borrower)

    with boa.reverts():
        controller.add_collateral(add_collateral, borrower, sender=attacker)
    _assert_position_unchanged(controller, amm, borrower, before)

    with boa.reverts():
        controller.borrow_more(add_collateral, more_debt, borrower, sender=attacker)
    _assert_position_unchanged(controller, amm, borrower, before)

    with boa.reverts():
        controller.remove_collateral(add_collateral, borrower, sender=attacker)
    _assert_position_unchanged(controller, amm, borrower, before)

    with boa.reverts():
        controller.repay(repay_amount, borrower, sender=attacker)
    _assert_position_unchanged(controller, amm, borrower, before)

    with boa.reverts("Not enough rekt"):
        controller.liquidate(borrower, before["state"][1], sender=attacker)
    _assert_position_unchanged(controller, amm, borrower, before)

    with boa.reverts():
        amm.deposit_range(
            borrower,
            collateral_amount,
            before["ticks"][0],
            before["ticks"][1],
            sender=attacker,
        )
    _assert_position_unchanged(controller, amm, borrower, before)

    with boa.reverts():
        amm.withdraw(borrower, 10**18, sender=attacker)
    _assert_position_unchanged(controller, amm, borrower, before)

    trader = boa.env.generate_address("trader")
    boa.deal(borrowed_token, trader, debt_amount)
    max_approve(borrowed_token, amm, sender=trader)

    ticks_before_swap = tuple(amm.read_user_tick_numbers(borrower))
    state_before_swap = tuple(controller.user_state(borrower))
    active_band_before_swap = amm.active_band()

    amm.exchange(0, 1, debt_amount, 0, sender=trader)

    state_after_swap = tuple(controller.user_state(borrower))
    assert tuple(amm.read_user_tick_numbers(borrower)) == ticks_before_swap
    assert (
        state_after_swap[:2] != state_before_swap[:2]
        or amm.active_band() != active_band_before_swap
    )

    exact_out = max(state_after_swap[0] // 1000, 1)
    required_in = amm.get_dx(0, 1, exact_out)
    trader2 = boa.env.generate_address("trader2")
    boa.deal(borrowed_token, trader2, required_in)
    max_approve(borrowed_token, amm, sender=trader2)

    ticks_before_swap_dy = tuple(amm.read_user_tick_numbers(borrower))
    state_before_swap_dy = tuple(controller.user_state(borrower))
    active_band_before_swap_dy = amm.active_band()

    amm.exchange_dy(0, 1, exact_out, required_in, sender=trader2)

    state_after_swap_dy = tuple(controller.user_state(borrower))
    assert tuple(amm.read_user_tick_numbers(borrower)) == ticks_before_swap_dy
    assert (
        state_after_swap_dy[:2] != state_before_swap_dy[:2]
        or amm.active_band() != active_band_before_swap_dy
    )


def test_unapproved_bad_liquidation_is_the_exception(
    controller,
    amm,
    admin,
    price_oracle,
    borrowed_token,
    create_loan,
):
    borrower, _, _ = create_loan(1, 1)
    liquidator = boa.env.generate_address("liquidator")

    assert not controller.approval(borrower, liquidator)

    price_oracle.set_price(price_oracle.price() // 2, sender=admin)
    assert controller.health(borrower) < 0

    tokens_needed = controller.tokens_to_liquidate(borrower)
    boa.deal(borrowed_token, liquidator, tokens_needed)
    max_approve(borrowed_token, controller, sender=liquidator)

    controller.liquidate(
        borrower, controller.user_state(borrower)[1], sender=liquidator
    )

    assert controller.user_state(borrower)[3] == 0
    assert not amm.has_liquidity(borrower)
