# Lending Monetary Policies

This directory contains monetary policies specifically designed for lending markets (where users supply assets to be borrowed). Unlike mint markets where crvUSD is minted against collateral, lending markets involve borrowing existing assets (like crvUSD) supplied by lenders.

## Policies

### `SemilogMonetaryPolicy.vy`
A standalone policy where the borrow rate depends solely on the market's utilization.
- **Formula:** `log(rate) = utilization * (log(rate_max) - log(rate_min)) + log(rate_min)`
- **Behavior:** The rate increases exponentially as utilization increases, between `min_rate` and `max_rate`.
- **Use Case:** General-purpose lending markets.

### `SusdeMonetaryPolicy.vy`
A specialized variation of `SecondaryMonetaryPolicy` (based on the same logic but for yield-bearing assets) where the "base rate" is derived from the yield of sUSDe (Ethena), rather than an AMM.
- **Base Rate:** Exponential Moving Average (EMA) of sUSDe's yield.
- **Use Case:** Markets involving sUSDe where the borrow rate should reflect the underlying yield of the asset.

**TODO:** More markets have adopted the logic from `SusdeMonetaryPolicy` (generic `EMAMonetaryPolicy`). This needs to be documented/added in a future PR.

## Deprecated

### `SecondaryMonetaryPolicy.vy`
**STATUS: DEPRECATED & DANGEROUS**
([View Source](https://github.com/curvefi/curve-stablecoin/blob/c4c32557aea01bf658d43e31a0276f88137f6ff7/curve_stablecoin/mpolicies/lend/SecondaryMonetaryPolicy.vy))

This policy calculated borrow rates based on a "base rate" (e.g., AMM rate) and utilization.
- **Risk:** It creates a dependency that can lead to **illiquidity for lenders**. If the base rate is low but utilization is high, the rate might not rise sufficiently to incentivize repayments or deposits, potentially locking lender funds.
- **Replacement:** Use `SemilogMonetaryPolicy` or other independent rate models that guarantee rate increases at high utilization regardless of external factors.
