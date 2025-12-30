# LLM Test Scaffold Guide

Use this as you fill scaffolded unit tests. Delete this README when the work is done (self-destruct).

## Naming & structure
- Keep the `test_default_behavior` prefix; only rename the suffix (e.g., `test_default_behavior_branch_1` -> `test_default_behavior_user_initiated_withdrawal`).
- Revert tests (`test_revert_*`) can be renamed, but keep the `test_revert_` prefix.
- Leave skip markers until implemented.

## Test layout & focus
- Keep tests localized under the contract’s folder (e.g., `tests/unitary/mpolicies/<contract>/`). Don’t mix concerns across modules.
- Write focused tests: assert the behavior of the function under test, not the internals of helpers that should be covered elsewhere.
- Prefer small, direct scenarios; avoid sprawling integration in unit tests. Reuse shared fixtures instead of re-implementing setup.

## Examples to mirror (read before writing)
- Logs + sequencing: `tests/unitary/controller/test_internal_repay_full.py` captures `filter_logs` immediately after the tx; avoid any extra contract calls in between.
- Internal wrappers: `tests/unitary/controller/test_internal_remove_from_list.py` and `test_internal_repay_full.py` inject minimal externals to hit internal logic, then call via `controller.inject.<fn>()`.
- Storage/eval checks: `tests/unitary/lending/vault/test_price_per_share_v.py` reads internal state with `contract.eval`; prefer public getters when available.
- State updates after ops: controller add/borrow tests (e.g., `tests/unitary/controller/test_add_collateral.py`) assert `amm.rate_time` moves forward after actions.
- Parametrized behaviors: `tests/controller/test_set_price_oracle.py` uses fixtures to override decimals/oracles and checks boundary conditions and reverts explicitly.
- Partial/branch coverage: `tests/unitary/controller/test_internal_repay_partial.py` drives both payer paths and reuses shared snapshots to assert money flows.

## What to assert
- Storage hints in comments: prefer public getters; otherwise `contract.eval("self.var")` is acceptable.
- Log hints: call `tests.utils.filter_logs(contract, "Event")` immediately after the transaction under test; avoid extra calls (even `eval`) before collecting logs because they count as contract calls.
- Default/branch tests cover non-revert paths; revert tests should assert failures via `boa.reverts()`.

## Internal function wrappers
- To exercise internal methods, inject a thin external wrapper via `contract.inject_function` (see `tests/unitary/controller/test_internal_remove_from_list.py` or `test_internal_repay_full.py`).
- Define wrappers with the same signature as the internal function, minimal logic, and call through `contract.inject.<fn_name>(...)` in tests.
- Keep these wrappers in module-scope fixtures (often `autouse=True`) and prefer reusing existing patterns over inventing new ones.

## Fixtures & conftest expectations
- Reuse existing fixtures from `tests/conftest.py` (proto, admin, controller/amm/vault, market_type parametrized as mint/lending, seed_liquidity/borrow_cap, price_oracle, monetary_policy, etc.).
- Lending unit tests may also use `tests/unitary/lending/conftest.py` fixtures (e.g., `market_type` override to lending, `make_debt`, `deposit_into_vault`).
- Prefer module-scope fixtures; avoid creating new fixtures or changing scopes without explicit user discussion.
- If you need new setup/fixtures or to reshape conftest behavior, pause and discuss with the user before designing them.

## Cleanup
- After the test suite is implemented, remove this README to avoid committing scaffolding instructions.
