DEAD_SHARES: constant(uint256) = 1000
MAX_TICKS_UINT: constant(uint256) = 50
MIN_TICKS_UINT: constant(uint256) = 4

@internal
@pure
def get_y_effective(
    collateral: uint256,
    N: uint256,
    discount: uint256,
    sqrt_band_ratio: uint256,
    A: uint256
) -> uint256:
    """
    @notice Intermediary method which calculates y_effective defined as x_effective / p_base,
            however discounted by loan_discount.
            x_effective is an amount which can be obtained from collateral when liquidating
    @param collateral Amount of collateral to get the value for
    @param N Number of bands the deposit is made into
    @param discount Loan discount at 1e18 base (e.g. 1e18 == 100%)
    @return y_effective
    """
    # x_effective = sum_{i=0..N-1}(y / N * p(n_{n1+i})) =
    # = y / N * p_oracle_up(n1) * sqrt((A - 1) / A) * sum_{0..N-1}(((A-1) / A)**k)
    # === d_y_effective * p_oracle_up(n1) * sum(...) === y_effective * p_oracle_up(n1)
    # d_y_effective = y / N / sqrt(A / (A - 1))
    # d_y_effective: uint256 = collateral * unsafe_sub(10**18, discount) / (SQRT_BAND_RATIO * N)
    # Make some extra discount to always deposit lower when we have DEAD_SHARES rounding
    d_y_effective: uint256 = unsafe_div(
        collateral * unsafe_sub(
            10**18, min(discount + unsafe_div((DEAD_SHARES * 10**18), max(unsafe_div(collateral, N), DEAD_SHARES)), 10**18)
        ),
        unsafe_mul(sqrt_band_ratio, N))
    y_effective: uint256 = d_y_effective
    Aminus1: uint256 = A - 1
    for i: uint256 in range(1, MAX_TICKS_UINT):
        if i == N:
            break
        d_y_effective = unsafe_div(d_y_effective * Aminus1, A)
        y_effective = unsafe_add(y_effective, d_y_effective)
    return y_effective