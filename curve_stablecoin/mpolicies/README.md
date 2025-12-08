# Monetary Policy Controller Compatibility Guide

Snapshot: Ethereum mainnet block 23969844

## Version fingerprints (on-chain detection)
- **v1 (AggMonetaryPolicy)**: no `controllers()` view, no `min_debt_candles()`, no `extra_const()`.
- **v2 (AggMonetaryPolicy2)**: has `controllers(uint256)`; no `min_debt_candles()`, no `extra_const()`.
- **v3 (AggMonetaryPolicy3)**: has `min_debt_candles(address)`; no `extra_const()`.
- **v3c (AggMonetaryPolicy3c)**: `min_debt_candles(address)` + `extra_const()` base-rate additive.

## Mainnet factory 0xC9332fdCB1C491Dcc683bAe86Fe3cb70360738BC
On-chain mapping (block 23969844):

- Controller 0: 0x8472A9A7632b173c8Cf3a86D3afec50c35548e76 → policy 0xc684432FD6322c6D58b6bC5d28B18569aA0AD0A1 → **v1** (collateral 0xac3E018457B222d93114458476f3E3416Abbe38F / `sfrxETH`). This is the only v1 left; no frxETH collateral is present in this factory.
- Controller 1: 0x100dAa78fC509Db39Ef7D04DE0c1ABD299f4C6CE → policy 0x8D76F31E7C3b8f637131dF15D9b4a3F8ba93bd75 → **v3c** (`extra_const = 475646879`, collateral wstETH 0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0).
- Controller 2: 0x4e59541306910aD6dC1daC0AC9dFB29bD9F15c67 → policy 0x8c5A7F011f733fBb0A6c969c058716d5CE9bc933 → **v3** (collateral WBTC 0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599).
- Controller 3: 0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635 → policy 0x8c5A7F011f733fBb0A6c969c058716d5CE9bc933 → **v3** (collateral WETH 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2).
- Controller 4: 0xEC0820EfafC41D8943EE8dE495fC9Ba8495B15cf → policy 0x8D76F31E7C3b8f637131dF15D9b4a3F8ba93bd75 → **v3c** (`extra_const = 475646879`, collateral sfrxETH 0xac3E018457B222d93114458476f3E3416Abbe38F).
- Controller 5: 0x1C91da0223c763d2e0173243eAdaA0A2ea47E704 → policy 0x8c5A7F011f733fBb0A6c969c058716d5CE9bc933 → **v3** (collateral tBTC 0x18084fbA666a33d37592fA2633fD49a74DD93a88).
- Controller 6: 0x652aEa6B22310C89DCc506710CaD24d2Dba56B11 → policy 0x8D76F31E7C3b8f637131dF15D9b4a3F8ba93bd75 → **v3c** (`extra_const = 475646879`, collateral weETH 0xCd5fE23C85820F7B72D0926FC9b05b43E359b7ee).
- Controller 7: 0xf8C786b1064889fFd3c8A08B48D5e0c159F4cBe3 → policy 0x8c5A7F011f733fBb0A6c969c058716d5CE9bc933 → **v3** (collateral cbBTC 0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf).
- Controller 8: 0x8aca5A776a878Ea1F8967e70a23b8563008f58Ef → policy 0x8c5A7F011f733fBb0A6c969c058716d5CE9bc933 → **v3** (collateral LBTC 0x8236a87084f8B84306f72007F36F2618A5634494).

Counts at block 23969844: v1 = 1 (legacy sfrxETH), v2 = 0 observed, v3 = 5, v3c = 3.

## Why v3/v3c exists (early rate-update bug)

Old controllers compiled with Vyper 0.3.7 call `rate_write()` before updating debt, so the monetary policy sees stale `total_debt()`/`debt_for` when applying ceiling utilization math (see AggMonetaryPolicy2 lines ~218-232). Example (buggy ordering):

```python
# Old controller pattern (vyper 0.3.7)
rate_mul: uint256 = self._rate_mul_w()  # calls monetary_policy.rate_write() first
# debt is updated only after rate_write()
total_debt: uint256 = self._total_debt.initial_debt * rate_mul / self._total_debt.rate_mul + debt
self._total_debt.initial_debt = total_debt
self._total_debt.rate_mul = rate_mul
```

Impact: stale debt leads to incorrect per-market rates, especially near debt ceilings.

Newer controllers (Vyper 0.3.9+) fix the ordering so debt state is updated before rate calculations.

## Workaround: AggMonetaryPolicy3 / 3c

v3 introduces 12h debt "candles" (min of last two half-day buckets) to smooth the stale-read issue. v3c adds `extra_const` as a base-rate floor on top of the v3 formula:

```
v3:  rate = rate0 * exp(power) / 1e18
v3c: rate = rate0 * exp(power) / 1e18 + extra_const
```

Trade-off: slight lag (up to 12h) but avoids mispricing from timing skew in old controllers.

## Compatibility guidance

- **Use v3/v3c** with legacy controllers compiled under Vyper 0.3.7 (factory indices 0-3). v3c is just v3 + base-rate additive.
- **Use v2** with fixed controllers (Vyper 0.3.9+) when you want immediate responsiveness and do not need candle smoothing. (Note: as of block 23969844, this factory still uses v3/v3c even for newer controllers; no v2 observed.)
- **v1** remains only on the legacy sfrxETH controller (index 0) in this factory;

## Reproduce (mainnet)

```sh
RPC=https://1rpc.io/eth
FACT=0xC9332fdCB1C491Dcc683bAe86Fe3cb70360738BC
cast block-number --rpc-url $RPC
cast call $FACT "n_collaterals()(uint256)" --rpc-url $RPC
# For each i: controller, policy, and probes
cast call $FACT "controllers(uint256)(address)" <i> --rpc-url $RPC
cast call <controller> "monetary_policy()(address)" --rpc-url $RPC
cast call <policy> "extra_const()(uint256)" --rpc-url $RPC 2>/dev/null
cast call <policy> "min_debt_candles(address)((uint256,uint256,uint256))" 0x0 --rpc-url $RPC 2>/dev/null
```

## References
- AggMonetaryPolicy2: `curve_stablecoin/mpolicies/AggMonetaryPolicy2.vy`
- AggMonetaryPolicy3: `curve_stablecoin/mpolicies/AggMonetaryPolicy3.vy`
- AggMonetaryPolicy3c: `curve_stablecoin/mpolicies/AggMonetaryPolicy3c.vy`
- Controller factory: 0xC9332fdCB1C491Dcc683bAe86Fe3cb70360738BC
