import boa

from tests.utils.constants import DEAD_SHARES, MIN_SHARES_ALLOWED, MAX_UINT256


def _ceil_div(x, y):
    return (x + y - 1) // y


def _find_frac_for_remaining(shares, remaining):
    ds = shares - remaining
    lower = _ceil_div(ds * 10**18, shares)
    upper = ((ds + 1) * 10**18 - 1) // shares
    if lower <= upper:
        return lower
    return None


def test_min_shares(amm, collateral_token, admin, accounts):
    user = accounts[0]
    collateral_precision = 10 ** (18 - collateral_token.decimals())
    collateral_per_band = MIN_SHARES_ALLOWED // (collateral_precision * DEAD_SHARES)
    if collateral_per_band == 0:
        collateral_per_band = 1

    boa.deal(collateral_token, user, collateral_per_band * 4)

    active_band = amm.active_band()
    with boa.env.prank(admin):
        amm.deposit_range(
            user, collateral_per_band * 4, active_band - 4, active_band - 1
        )


def test_min_shares_fails(amm, collateral_token, admin, accounts):
    user = accounts[0]
    collateral_per_band = 1000
    boa.deal(collateral_token, user, collateral_per_band * 4)

    active_band = amm.active_band()
    collateral_precision = 10 ** (18 - collateral_token.decimals())
    with boa.env.prank(admin):
        if (
            collateral_precision * DEAD_SHARES * collateral_per_band
            >= MIN_SHARES_ALLOWED
        ):
            # doesn't fail for coins with low decimals
            amm.deposit_range(
                user, collateral_per_band * 4, active_band - 4, active_band - 1
            )
        else:
            with boa.reverts("Amount too low"):
                amm.deposit_range(
                    user, collateral_per_band * 4, active_band - 4, active_band - 1
                )


def test_min_shares_withdraw(amm, collateral_token, admin, accounts):
    user = accounts[0]
    collateral_precision = 10 ** (18 - collateral_token.decimals())
    collateral_amount = _ceil_div(
        2 * MIN_SHARES_ALLOWED, collateral_precision * DEAD_SHARES
    )
    boa.deal(collateral_token, user, collateral_amount)

    active_band = amm.active_band()
    with boa.env.prank(admin):
        amm.deposit_range(user, collateral_amount, active_band - 1, active_band - 1)

        shares = amm.eval(f"self.user_shares[{user}].ticks[0]")
        frac = None
        for remaining in range(
            MIN_SHARES_ALLOWED,
            MIN_SHARES_ALLOWED + shares // 10**18 + 3,
        ):
            frac = _find_frac_for_remaining(shares, remaining)
            if frac is not None:
                break

        assert frac is not None
        amm.withdraw(user, frac)

        assert amm.eval(f"self.user_shares[{user}].ticks[0]") >= MIN_SHARES_ALLOWED


def test_min_shares_withdraw_fails(amm, collateral_token, admin, accounts):
    user = accounts[0]
    collateral_precision = 10 ** (18 - collateral_token.decimals())
    collateral_amount = _ceil_div(
        2 * MIN_SHARES_ALLOWED, collateral_precision * DEAD_SHARES
    )
    boa.deal(collateral_token, user, collateral_amount)

    active_band = amm.active_band()
    with boa.env.prank(admin):
        amm.deposit_range(user, collateral_amount, active_band - 1, active_band - 1)

        shares = amm.eval(f"self.user_shares[{user}].ticks[0]")
        frac = None
        for remaining in range(
            MIN_SHARES_ALLOWED - 1,
            MIN_SHARES_ALLOWED - (shares // 10**18 + 3),
            -1,
        ):
            frac = _find_frac_for_remaining(shares, remaining)
            if frac is not None:
                break

        assert frac is not None
        with boa.reverts("Amount left too low"):
            amm.withdraw(user, frac)


def test_share_price(
    amm,
    collateral_token,
    borrowed_token,
    admin,
    accounts,
):
    user = accounts[0]
    collateral_per_band = 10 ** collateral_token.decimals()

    boa.deal(collateral_token, user, 10**18 * 10 ** collateral_token.decimals())
    boa.deal(borrowed_token, user, 10**18 * 10 ** borrowed_token.decimals())
    boa.deal(collateral_token, amm, 10**18 * 10 ** collateral_token.decimals())
    boa.deal(borrowed_token, amm, 10**18 * 10 ** borrowed_token.decimals())

    active_band = amm.active_band()
    N = 4
    SHARE_PRICE_THRESHOLD = 10**11
    low_band = active_band - N
    high_band = active_band - 1
    bands = list(range(low_band, high_band + 1))
    with boa.env.prank(admin):
        amm.deposit_range(user, collateral_per_band * N, low_band, high_band)

    def cps(band):
        total_shares = MIN_SHARES_ALLOWED
        return (amm.bands_y(band) + 1) / (total_shares + DEAD_SHARES)

    cps_initial = cps(low_band)
    assert cps_initial < SHARE_PRICE_THRESHOLD, "Price per share is too high"

    # trade back and forth
    with boa.env.prank(user):
        collateral_token.approve(amm, MAX_UINT256)
        borrowed_token.approve(amm, MAX_UINT256)

        bands_y = [amm.bands_y(b) for b in bands]
        dy = sum(bands_y)
        dy, dx = amm.get_dydx(0, 1, dy)
        amm.exchange_dy(0, 1, dy, MAX_UINT256)

        bands_x = [amm.bands_x(b) for b in bands]
        dx = sum(bands_x)
        dx, dy = amm.get_dydx(1, 0, dx)
        amm.exchange_dy(1, 0, dx, MAX_UINT256)

    cps = cps(low_band)
    assert cps < SHARE_PRICE_THRESHOLD, "Price per share is too high"
    assert cps / cps_initial < 1.05, "Inflation of share price is too high"
