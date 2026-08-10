"""A band holding dust `x` and no `y` makes the AMM's view math divide by zero.

`_get_y0(x, 0, p_o, p_o_up)` (`AMM.vy:432`) computes
`b = p_o_up * (A - 1) * x // p_o` and returns `b * 1e18 // (A * p_o)`, so `y0`
truncates to **0** once `x` falls below roughly `p_o / 1e18` - a few thousand wei.
`f`, `g` and `Inv` are all proportional to `y0`, so they go to 0 with it, and the
next line divides by one of them:

    get_xy_up:1429            x_o = sub_or_zero(Inv // (g + y_o), f)
    get_amount_for_price:1583 xnew = sub_or_zero(Inv // (g + ynew), f)

The band has to be *below* the active band - `get_xy_up` reads `y` only for
`n >= n_active`, so a crossed band always presents `y == 0` - with the oracle
price back inside it, which is just the AMM lagging an oracle that moved up.

Reachable in production: the `lm_callback` fuzz run (run2) hit it organically and
dumped `bands_x = {45: 1261113747837, 46: 1, 47: 4}`, `bands_y = {47: 20288}` -
band 46 holding 1 wei of borrowed token and no collateral. Conversion alone cannot
produce it (a band's minimum deposit is ~100 wei of collateral, worth ~100x the
truncation point once converted), so the dust comes from withdrawal rounding -
`dx = (x + 1) * ds // s` in `_withdraw` leaves a few wei behind whenever shares
remain. This test writes the same state directly instead of hunting for the
rounding that produces it.

Impact: `get_x_down` / `get_y_up` back `controller._health` (`controller.vy:1187`)
and `ControllerView`, so a position with such a band has unreadable health and
cannot be liquidated, and `repay` / `remove_collateral` / `borrow_more` revert on
it too. `get_amount_for_price` breaks quoting for the whole AMM while the price is
in that band. The value at risk is dust, but the liveness loss is not.
"""

import boa
import pytest

from tests.utils import mint_for_testing

BAND = 5


@pytest.fixture
def dust_band(price_oracle, amm, collateral_token, borrowed_token, admin):
    """Fill one band, convert it to borrowed token, then leave `x` wei in it."""

    def f(x):
        user = boa.env.generate_address()
        with boa.env.prank(user):
            collateral_token.approve(amm.address, 2**256 - 1)
            borrowed_token.approve(amm.address, 2**256 - 1)

        deposit = 10 ** collateral_token.decimals()
        with boa.env.prank(admin):
            amm.deposit_range(user, deposit, BAND, BAND)
            mint_for_testing(collateral_token, amm.address, deposit)

        # Buy the whole band out, so it holds borrowed token and no collateral
        boa.env.time_travel(600)  # to reset the prev p_o counter
        mint_for_testing(borrowed_token, user, 2**128)
        amm.exchange_dy(0, 1, deposit, 2**128, sender=user)
        assert amm.bands_y(BAND) == 0
        assert amm.bands_x(BAND) > 0
        assert amm.active_band() >= BAND

        # Dust left over by rounding, and an oracle that has moved back into the
        # band without anyone arbitraging the AMM yet
        amm.eval(f"self.bands_x[{BAND}] = {x}")
        p_o = (amm.p_oracle_up(BAND) + amm.p_oracle_down(BAND)) // 2
        price_oracle.set_price(p_o, sender=admin)
        boa.env.time_travel(600)
        assert amm.p_oracle_down(BAND) <= amm.price_oracle() <= amm.p_oracle_up(BAND)

        return user, p_o

    return f


@pytest.mark.parametrize("x", [1, 4])  # both seen in run2's storage dump
@pytest.mark.xfail(
    strict=True,
    reason="C: y0 truncates to 0 on a dust band and the view math divides by it. "
    "Drop this marker together with the `if y0 == 0` guards in AMM.vy",
)
def test_dust_band_views_do_not_revert(dust_band, amm, x):
    user, p_o = dust_band(x)

    # The band is worth less than a wei of collateral, and it is the user's only
    # one, so it should contribute nothing - `sub_or_zero` already clamps these
    # to 0 wherever the division is defined, which is the safe direction for
    # health. Not reverting is the point; the values pin the safe direction
    assert amm.get_y_up(user) == 0
    assert amm.get_x_down(user) == 0
    amm.get_amount_for_price(p_o)  # quoting must stay up for the whole AMM


@pytest.mark.parametrize("x", [1, 4])
def test_dust_band_swaps_are_unaffected(dust_band, amm, x):
    """Only the view math is broken.

    `_get_p` returns early on `y == 0` (`AMM.vy:479`) without ever computing
    `y0`, and `_calc_swap` skips the band behind its `if y != 0: if g != 0:` /
    `if x != 0: if f != 0:` guards (`AMM.vy:872`, `909`).
    """
    dust_band(x)

    # Top of the band, since it holds only borrowed token
    assert amm.get_p() == pytest.approx(amm.p_current_up(BAND), rel=1e-9)
    # Nothing left to buy anywhere in the AMM
    assert amm.get_dy(0, 1, 10**6) == 0


def test_band_above_the_truncation_point_is_fine(dust_band, amm):
    """Same shape of state, but `x` large enough that `y0` survives.

    Pins the trigger to the truncation rather than to "band with no collateral".
    `10**20` is far above the truncation point (~2000 wei for this band) and also
    clears both COLLATERAL_PRECISION and BORROWED_PRECISION for every decimals
    parametrisation, so the results stay nonzero instead of flooring back to 0.
    """
    user, p_o = dust_band(10**20)

    assert amm.get_y_up(user) > 0
    assert amm.get_x_down(user) > 0
    assert amm.get_amount_for_price(p_o)[0] > 0
