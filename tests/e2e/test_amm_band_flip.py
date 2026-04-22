import boa
import pytest

from tests.utils import max_approve


N1 = 1
N2 = 5
N_BANDS = N2 - N1 + 1
ORACLE_STEP_NUMERATOR = 995
ORACLE_STEP_DENOMINATOR = 1000
MAX_STEPS = 200


@pytest.fixture(scope="module")
def collateral_decimals():
    return 18


@pytest.fixture(scope="module")
def borrowed_decimals():
    return 18


def test_exact_in_round_trip_across_amm_bands(
    amm,
    controller,
    price_oracle,
    collateral_token,
    borrowed_token,
    admin,
):
    depositor = boa.env.generate_address("depositor")
    trader = boa.env.generate_address("trader")
    deposit_amount = N_BANDS * 10 ** collateral_token.decimals()

    with boa.env.prank(trader):
        max_approve(borrowed_token, amm.address)
        max_approve(collateral_token, amm.address)

    # Seed liquidity above the active band so oracle moves force the AMM to
    # traverse the deposited range in both directions.
    with boa.env.prank(controller.address):
        amm.deposit_range(depositor, deposit_amount, N1, N2)
    boa.deal(
        collateral_token,
        amm.address,
        collateral_token.balanceOf(amm.address) + deposit_amount,
    )

    initial_oracle_price = price_oracle.price()
    initial_y = sum(amm.bands_y(n) for n in range(N1, N2 + 1))
    initial_active_band = amm.active_band()

    # Walk the oracle down until the AMM price is below it, which creates a
    # real upward trade path rather than assuming one exists after one step.
    lowered_oracle_price = initial_oracle_price
    for _ in range(MAX_STEPS):
        if amm.get_p() < lowered_oracle_price:
            break
        lowered_oracle_price = (
            lowered_oracle_price * ORACLE_STEP_NUMERATOR // ORACLE_STEP_DENOMINATOR
        )
        with boa.env.prank(admin):
            price_oracle.set_price(lowered_oracle_price)
    else:
        raise AssertionError("oracle walk did not create a tradable price gap")

    borrowed_step = max(
        deposit_amount * lowered_oracle_price // (100 * 10**18),
        1,
    )

    upward_trades = 0
    for _ in range(MAX_STEPS):
        current_price = amm.get_p()
        if current_price >= lowered_oracle_price:
            break

        boa.deal(
            borrowed_token,
            trader,
            borrowed_token.balanceOf(trader) + borrowed_step,
        )

        band_before = amm.active_band()
        with boa.env.prank(trader):
            amm.exchange(0, 1, borrowed_step, 0)

        band_after = amm.active_band()
        price_after = amm.get_p()
        if band_before == band_after:
            assert price_after >= current_price
        assert amm.p_current_down(band_after) <= price_after
        assert price_after <= amm.p_current_up(band_after)
        upward_trades += 1

    assert upward_trades > 0
    assert amm.active_band() > initial_active_band
    assert sum(amm.bands_y(n) for n in range(N1, N2 + 1)) < initial_y

    x_after_up = sum(amm.bands_x(n) for n in range(N1, N2 + 1))
    y_after_up = sum(amm.bands_y(n) for n in range(N1, N2 + 1))
    assert x_after_up > 0

    # Walk the oracle back up until the AMM price is above it, then sell
    # collateral back through the same band range.
    raised_oracle_price = lowered_oracle_price
    for _ in range(MAX_STEPS):
        if amm.get_p() > raised_oracle_price:
            break
        raised_oracle_price = (
            raised_oracle_price * ORACLE_STEP_DENOMINATOR // ORACLE_STEP_NUMERATOR
        )
        with boa.env.prank(admin):
            price_oracle.set_price(raised_oracle_price)
    else:
        raise AssertionError("oracle walk did not create a tradable price gap")

    collateral_step = max(deposit_amount // 100, 1)
    downward_trades = 0
    for _ in range(MAX_STEPS):
        current_price = amm.get_p()
        if current_price <= raised_oracle_price:
            break

        boa.deal(
            collateral_token,
            trader,
            collateral_token.balanceOf(trader) + collateral_step,
        )

        band_before = amm.active_band()
        with boa.env.prank(trader):
            amm.exchange(1, 0, collateral_step, 0)

        band_after = amm.active_band()
        price_after = amm.get_p()
        if band_before == band_after:
            assert price_after <= current_price
        assert amm.p_current_down(band_after) <= price_after
        assert price_after <= amm.p_current_up(band_after)
        downward_trades += 1

    assert downward_trades > 0
    assert sum(amm.bands_x(n) for n in range(N1, N2 + 1)) < x_after_up
    assert sum(amm.bands_y(n) for n in range(N1, N2 + 1)) > y_after_up


def test_exact_out_quotes_match_execution_while_flipping_bands(
    amm,
    controller,
    price_oracle,
    collateral_token,
    borrowed_token,
    admin,
):
    depositor = boa.env.generate_address("depositor")
    trader = boa.env.generate_address("trader")
    deposit_amount = N_BANDS * 10 ** collateral_token.decimals()

    with boa.env.prank(trader):
        max_approve(borrowed_token, amm.address)
        max_approve(collateral_token, amm.address)

    # Seed the same range and then move the oracle so exact-output trades
    # cross bands under a realistic price gap.
    with boa.env.prank(controller.address):
        amm.deposit_range(depositor, deposit_amount, N1, N2)
    boa.deal(
        collateral_token,
        amm.address,
        collateral_token.balanceOf(amm.address) + deposit_amount,
    )

    initial_oracle_price = price_oracle.price()
    lowered_oracle_price = initial_oracle_price
    for _ in range(MAX_STEPS):
        if amm.get_p() < lowered_oracle_price:
            break
        lowered_oracle_price = (
            lowered_oracle_price * ORACLE_STEP_NUMERATOR // ORACLE_STEP_DENOMINATOR
        )
        with boa.env.prank(admin):
            price_oracle.set_price(lowered_oracle_price)
    else:
        raise AssertionError("oracle walk did not create a tradable price gap")

    desired_collateral_out = max(deposit_amount // 10, 1)
    quoted_borrowed_in = amm.get_dx(0, 1, desired_collateral_out)
    boa.deal(
        borrowed_token,
        trader,
        borrowed_token.balanceOf(trader) + quoted_borrowed_in,
    )

    band_before = amm.active_band()
    price_before = amm.get_p()
    with boa.env.prank(trader):
        spent, received = amm.exchange_dy(
            0, 1, desired_collateral_out, quoted_borrowed_in
        )

    assert spent == quoted_borrowed_in
    assert received == desired_collateral_out
    band_after = amm.active_band()
    price_after = amm.get_p()
    if band_before == band_after:
        assert price_after >= price_before
    assert amm.p_current_down(band_after) <= price_after
    assert price_after <= amm.p_current_up(band_after)

    borrowed_in_bands = sum(amm.bands_x(n) for n in range(N1, N2 + 1))
    assert borrowed_in_bands > 0

    raised_oracle_price = price_oracle.price()
    for _ in range(MAX_STEPS):
        if amm.get_p() > raised_oracle_price:
            break
        raised_oracle_price = (
            raised_oracle_price * ORACLE_STEP_DENOMINATOR // ORACLE_STEP_NUMERATOR
        )
        with boa.env.prank(admin):
            price_oracle.set_price(raised_oracle_price)
    else:
        raise AssertionError("oracle walk did not create a tradable price gap")

    desired_borrowed_out = max(borrowed_in_bands // 4, 1)
    quoted_collateral_in = amm.get_dx(1, 0, desired_borrowed_out)
    boa.deal(
        collateral_token,
        trader,
        collateral_token.balanceOf(trader) + quoted_collateral_in,
    )

    band_before = amm.active_band()
    price_before = amm.get_p()
    with boa.env.prank(trader):
        spent, received = amm.exchange_dy(
            1, 0, desired_borrowed_out, quoted_collateral_in
        )

    assert spent == quoted_collateral_in
    assert received == desired_borrowed_out
    band_after = amm.active_band()
    price_after = amm.get_p()
    if band_before == band_after:
        assert price_after <= price_before
    assert amm.p_current_down(band_after) <= price_after
    assert price_after <= amm.p_current_up(band_after)
