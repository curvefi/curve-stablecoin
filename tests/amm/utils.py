from tests.utils.constants import DEAD_SHARES


def deposit_amount_too_low(amm, amount, n1, n2, collateral_precision):
    n_bands = n2 - n1 + 1
    total_amount = amount * collateral_precision
    y_per_band = total_amount // n_bands
    if y_per_band <= 100:
        return True

    for i, band in enumerate(range(n1, n2 + 1)):
        y = y_per_band
        if i == 0:
            y = total_amount - y_per_band * (n_bands - 1)
        total_y = amm.bands_y(band)
        s = amm.eval(f"self.total_shares[{band}]")
        ds = ((s + DEAD_SHARES) * y) // (total_y + 1)
        if ds == 0:
            return True

    return False
