# Stateful Testing

Stateful tests are the highest-value fuzz tests in this repository. They model a
protocol surface as a sequence of allowed actions, then check invariants after
Hypothesis has generated many action sequences. The local standard should be the
twocrypto-ng stateful suite:

- [twocrypto-ng/tests/stateful](https://github.com/curvefi/twocrypto-ng/tree/main/tests/stateful)
- A `RuleBasedStateMachine` base owns setup, tracked model state, wrapped
  protocol actions, and shared invariants.
- A common strategies module owns reusable input and deployment strategies.
- Subclasses add rules progressively, from narrower behavior to broader behavior.
- Rules call the wrapped actions instead of touching contracts directly.
- Invariants assert durable protocol truths and local model consistency.
- `note(...)` and `event(...)` explain generated scenarios well enough that a
  failure can be understood from the pytest output.

## Current State

The current suite is useful but uneven.

`tests/fuzz/stateful/test_controller_stateful.py` is the main controller state
machine. It creates mint markets from Hypothesis strategies, tracks open loan
users, and covers `create_loan`, `repay`, `borrow_more`, `remove_collateral`,
time advancement, open-user accounting, and liquidation cleanup.

`tests/fuzz/stateful/stateful_base.py` owns the shared Llamalend state-machine
model. It initializes markets, wraps controller and vault operations, keeps local
tracking in sync, and defines common invariants. New stateful suites should add
rules on top of this base instead of calling contracts directly from rules.

`tests/fuzz/stateful/test_lend_controller_stateful.py` extends that controller
machine for lending markets. It reuses the controller rules and adds vault
`deposit` and `withdraw` actions.

`tests/fuzz/strategies.py` is the shared strategy module. It currently defines
common market deployment strategies such as `mint_markets`, `lend_markets`, and
`ticks`, which are already used by the stateful controller suites. It should also
be used by ordinary fuzz tests when they need the same concepts.

`tests/stableborrow/stabilize/stateful/` is older peg-keeper stateful coverage.
It still uses `run_state_machine_as_test` and class attribute fixture injection
because the setup predates the current strategy-first style. Keep it working, but
do not copy that pattern for new tests.

Several older stateful tests still live outside `tests/fuzz/stateful`, including
`tests/stableborrow/test_create_repay_stateful.py`, `tests/lending/test_bigfuzz.py`,
`tests/lending/test_vault.py`, and interest or health state machines. Treat these
as legacy coverage until they are moved or rewritten.

## Hypothesis Profiles

Shrinking is disabled for every local Hypothesis profile. Agents and humans can
read verbose failure traces now, while shrinking expensive EVM state machines
often spends a long time simplifying without producing a materially better
counterexample.

The global `tests/conftest.py` profile policy is:

- `default`: runs explicit, reuse, generate, and target phases only.
- `quick`: inherits `default`, then lowers `max_examples` and
  `stateful_step_count` for fast local checks.

Do not add profiles or per-test settings that include `Phase.shrink`.

## Running And Debugging

Run a stateful suite with verbose Hypothesis output:

```bash
python -m pytest --hypothesis-show-statistics --hypothesis-verbosity=verbose -s tests/fuzz/stateful/test_controller_stateful.py
```

Use the quick profile for a smoke run:

```bash
HYPOTHESIS_PROFILE=quick python -m pytest -s tests/fuzz/stateful/test_lend_controller_stateful.py
```

If a failure is hard to read, add or improve `note(...)` calls around the action
that generated it. Prefer notes that include:

- The rule name.
- The selected user or market role.
- Input amounts after decimal correction.
- Relevant pre-state and post-state values.
- Whether a revert was expected, ignored, or fatal.

Use `event(...)` for scenario classes you want counted in Hypothesis statistics,
such as liquidations found, full repayments, zero headroom, or allowed safe
reverts.

## Structure For New Suites

Put new stateful suites in `tests/fuzz/stateful/` unless they are explicitly
covering the legacy stabilizer area.

Use this shape:

1. Define strategy helpers before the state machine.
2. Define a base `RuleBasedStateMachine`.
3. Initialize with Hypothesis-native strategies in `@initialize(...)`.
4. Store every piece of off-chain model state on `self`.
5. Wrap each protocol action in a helper method when it mutates both contracts
   and model state.
6. Expose rules that draw runtime-dependent values with `data.draw(...)`.
7. Keep invariants small, named, and durable.
8. End the file with `TestName = StateMachineName.TestCase`.

Prefer this pattern:

```python
class ControllerStateful(RuleBasedStateMachine):
    @initialize(market=mint_markets())
    def initialize_market(self, market):
        self.controller = market["controller"]
        self.users = []

    def create_loan(self, user, collateral, debt, n):
        # Contract call and model update stay together.
        ...
        self.users.append(user)

    @rule(n=ticks, data=data())
    def create_loan_rule(self, n, data):
        user = boa.env.generate_address(f"user_{len(self.users)}")
        collateral, debt = data.draw(
            loan_amounts_for_create(self.controller, n),
            label="loan_amounts_for_create",
        )
        self.create_loan(user, collateral, debt, n)

    @invariant()
    def users_match_controller(self):
        assert set(self.users) == {
            self.controller.loans(i) for i in range(self.controller.n_loans())
        }


TestControllerStateful = ControllerStateful.TestCase
```

## Shared Strategies

twocrypto-ng uses a shared strategy file for both stateful setup and reusable
fuzz inputs. Its stateful tests import strategies such as `address` and
`pool_from_preset` from `tests/utils/strategies.py`; that module defines the
deployment parameter ranges, token strategies, pool factories, and preset-based
pool construction once, then every test suite consumes the same definitions.

Use the same pattern here. Put reusable Hypothesis strategies in
`tests/fuzz/strategies.py` when they describe common protocol concepts:

- market deployment, including mint and lending market parameters
- token decimals and token deployment
- AMM parameters such as `A`, fees, prices, and ticks
- loan parameter families shared by example-based fuzz and stateful tests
- user or address strategies
- runtime-independent bounds and presets

State-machine-specific draws can stay beside the state machine when they depend
on that machine's current mutable state, for example a selected user's live debt
or a vault's current `maxWithdraw`. If the helper only depends on contract
arguments and could be useful to a non-stateful fuzz test, move it to
`tests/fuzz/strategies.py`.

This keeps fuzz and stateful coverage aligned. When a bound changes, such as a
safer loan range or a decimals correction, the fix lands in one strategy instead
of being copied through several suites.

## Strategy Rules

Strategies should generate valid protocol inputs by construction. If an action is
known to revert for an input class, exclude that input class in the strategy or a
precondition instead of catching the revert in the rule.

Use `assume(...)` sparingly. It is acceptable when a bound can only be known at
runtime, but excessive filtering hides bad strategy design and slows the test.

Use `@composite` strategies for multi-step draws. They are easier to read and
debug than deep `flatmap(...)` chains.

Use `data.draw(...)` when a value depends on current contract state, such as a
user's current debt, vault shares, available headroom, total supply, or active
bands.

Keep values decimals-aware. Draw human-scale values when possible, then convert
to token precision. Avoid unbounded `2**256 - 1` ranges unless the purpose is
overflow coverage.

## Invariants

Good invariants usually fall into one of these categories:

- Local model state equals contract state.
- Aggregate accounting equals the sum of user-level accounting.
- Monotonic quantities only move in the expected direction.
- A recovery action remains possible from every generated state.
- Liquidation or cleanup rules leave no stale users in local tracking.

When an invariant needs to simulate destructive behavior, wrap it in
`boa.env.anchor()` so the state machine can continue from the original state.

Do not disable an invariant silently in a subclass. If a subclass needs a
different model, override the invariant with a short comment explaining why, as
in the twocrypto-ng ramping and imbalanced-liquidity suites.

## Fixtures

Do not use pytest fixtures directly in new state machines. Convert setup into
Hypothesis strategies instead.

`run_state_machine_as_test` is acceptable only for legacy tests that cannot yet
be migrated. New tests should use `StateMachine.TestCase` so pytest and
Hypothesis can report stateful statistics naturally.

## Failure Reproduction

When Hypothesis prints a failing example blob, keep it in the issue, PR, or
commit message while debugging. For durable regression coverage, prefer adding a
small deterministic test that captures the minimized scenario's intent rather
than checking in a large one-off generated state-machine script.

If the generated trace is already clear, do not spend time trying to shrink it.
Improve notes, reduce irrelevant strategy breadth, or add a targeted deterministic
test.
