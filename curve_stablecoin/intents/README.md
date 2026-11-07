# LlamaLend V2 Intents — contracts (draft)

Implementation of [INTENTS_PLAN.md](./INTENTS_PLAN.md). Vyper **0.4.3** (same as
master; nothing here needs 0.5.0 — plain `initializes`/`uses`/`exports` module
system).

## Files

| File | Role |
|---|---|
| `intent_lib.vy` | Stateful module: EIP-712 (domain, `Common` tail hashing, ECDSA + ERC-1271), nonce cancellation bitmap, cumulative partial-fill accounting (`filled`, `last_fill`), trigger conditions (price/health/rate vs controller+AMM), Dutch fee decay |
| `executor_core.vy` | Module `uses: intent_lib`. Six mirror intent types (1:1 with `IController`) as `@external` fns + shared internal `_do_*` primitives, infinite-approval memo, pause, fee payment |
| `IntentExecutorMirror.vy` | Deploy wrapper: `initializes` lib+core, `exports` the mirror API. For integrators & differential testing |
| `IntentExecutor.vy` | Deploy wrapper: `borrow()` + `repay()` only; dispatches onto core `_do_*` (open-vs-extend by `loan_exists`, withdraw/top-up legs pro-rata, full close via `MAX_UINT` sentinel) |
| `CallbackAdapter.vy` | Permissionless stateless callbacker (`callback_deposit/repay/liquidate`): decodes `(target, data)`, runs the solver route, approves controller back. No whitelist, no privileges |

## Key conventions

- `swap_min_out` is a **price floor** (output wei per `WAD` input), not an
  amount — composes with partial fills without pro-rata scaling; enforced by
  the executor via `user_state` deltas, so no trust in the callbacker.
- Fill units: debt units for debt-moving intents, collateral units for pure
  collateral moves. `_amount = MAX_UINT` fills the remainder.
- `Common.health_below` unset sentinel = `max_value(int256)`; uint conditions
  unset = `0`.
- Fee: Dutch decay `fee_start_bps → fee_end_bps` over `[decay_start, deadline]`,
  paid user → solver in the unit token via `transferFrom` (user grants ERC-20
  allowance to the executor; gasless flows are out of scope for now).
- Onboarding: `controller.approve(executor, True)` per market + token
  allowances to the executor.

## Build / integrate

Files import `curve_stablecoin.interfaces` / `curve_std.interfaces`, i.e. they
expect to live at `curve_stablecoin/intents/` in the repo:

```bash
git mv intents/*.vy curve_stablecoin/intents/
uv run vyper curve_stablecoin/intents/IntentExecutor.vy
uv run vyper curve_stablecoin/intents/IntentExecutorMirror.vy
uv run vyper curve_stablecoin/intents/CallbackAdapter.vy
```

Not compiled yet (written outside the repo tree) — expect minor
signature/type reconciliation against the real `IController.vyi` /
`curve_std` on first build, in particular:

- `IController.repay` / `liquidate` positional signatures and
  `CALLDATA_MAX_SIZE` (here `ROUTE_MAX = 4096`);
- token transfers use raw `IERC20 + default_return_value` — swap to
  `curve_std.token` (`tkn.transfer_from` etc.) for repo consistency;
- `liquidate` prefund path uses `tokens_to_liquidate(user, frac)`;
- whether `user_state` layout is `[collateral, borrowed, debt, N]` (assumed).

## TODO (per plan phases)

- unit + e2e fork tests (OP markets), stateful fuzz mirroring
  `tests/fuzz/stateful/*`; differential tests mirror-vs-direct-controller
- cancel-by-signature (relayed cancel), keeper reference bot, order relay
- `IIntentExecutor.vyi` / `IIntentExecutorMirror.vyi` interface files
