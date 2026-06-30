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
machine family. It runs against the single lending market initialized by the
base and layers rules incrementally:

- `CreateLoanStateful`: open loans only.
- `CreateRepayStateful`: open loans plus repayments.
- `BorrowMoreStateful`: adds more borrowing and collateral.
- `ControllerStateful`: adds collateral removal.

`tests/fuzz/stateful/stateful_base.py` owns the shared Llamalend state-machine
model. It initializes one lending market and one vault per stateful run, wraps
controller and vault operations, keeps local tracking in sync, and defines common
invariants. New stateful suites should add rules on top of this base instead of
calling contracts directly from rules.

`tests/fuzz/stateful/test_lend_controller_stateful.py` extends that controller
machine family for vault behavior. `LendDepositStateful` adds deposits, and
`LendControllerStateful` adds withdrawals.

Focused narrow suites steal coverage from the older stateful tests without
making the baseline controller suite monolithic:

- `test_vault_erc4626_stateful.py` covers ERC4626 vault paths such as
  `deposit`, `mint`, `withdraw`, `redeem`, receiver variants, owner variants,
  approvals, and preview return values.
- `test_controller_narrow_stateful.py` covers controller health-preview oracles,
  pure `add_collateral`, rate changes, borrow-cap changes, and debt-sum
  conservation.
- `test_amm_oracle_stateful.py` covers AMM accounting around observed bands and
  adiabatic oracle shifts that trade toward the old and new oracle prices.
- `test_liquidation_stateful.py` targets partial liquidation, self-liquidation,
  and callback liquidation rather than waiting for the baseline rules to find
  those states accidentally.

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
as legacy coverage until they are moved or rewritten. The goal is that
`tests/fuzz/stateful/` eventually covers every behavior that is still valuable in
those older suites, as focused subclasses rather than a recreated monolithic
BigFuzz. Until then, any old behavior not represented in the new suite should be
treated as an explicit migration gap, not as covered by proximity.

## Hypothesis Profiles

Shrinking is disabled for every local Hypothesis profile. Agents and humans can
read verbose failure traces now, while shrinking expensive EVM state machines
often spends a long time simplifying without producing a materially better
counterexample.

The global `tests/conftest.py` profile policy is:

- `default`: runs explicit, reuse, generate, and target phases only.
- `quick`: inherits `default`, then lowers `max_examples` and
  `stateful_step_count` for fast local checks.
- `ci-stateful`: inherits `default`, keeps shrinking disabled, and sets bounded
  but meaningful example and step counts for the `tests/fuzz/stateful` CI job.

Do not add profiles or per-test settings that include `Phase.shrink`.

## Running And Debugging

Run a stateful suite with verbose Hypothesis output:

```bash
python -m pytest --hypothesis-show-statistics --hypothesis-verbosity=verbose -s tests/fuzz/stateful/test_controller_stateful.py
```

Use the quick profile for a smoke run:

```bash
python -m pytest --hypothesis-profile=quick -s tests/fuzz/stateful/test_lend_controller_stateful.py
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

The Llamalend stateful tests use stable `stateful:*` event names for paths that
should be easy to audit:

- `stateful:create_loan`
- `stateful:repay`, `stateful:repay:full`, `stateful:repay:partial`
- `stateful:borrow_more`
- `stateful:remove_collateral`, `stateful:remove_collateral:none`
- `stateful:deposit`
- `stateful:withdraw`
- `stateful:time_forward`
- `stateful:liquidate`, `stateful:liquidate:none`
- `stateful:add_collateral`
- `stateful:health_preview:create_loan`, `stateful:health_preview:repay`
- `stateful:health_preview:add_collateral`,
  `stateful:health_preview:borrow_more`
- `stateful:rate_change`, `stateful:borrow_cap_change`
- `stateful:vault:deposit_for`, `stateful:vault:mint_for`
- `stateful:vault:withdraw`, `stateful:vault:redeem`
- `stateful:vault:withdraw_owner_for`, `stateful:vault:redeem_owner_for`
- `stateful:amm_exchange`
- `stateful:oracle_jump`
- `stateful:adiabatic_oracle_shift`
- `stateful:liquidate:partial`, `stateful:liquidate:self`,
  `stateful:liquidate:callback`
- `stateful:deposit_many`
- `stateful:create_many_loans`

These event names are part of the test observability surface. Prefer adding new
stable event names over relying on free-form `note(...)` text when a behavior
must be counted.

`tests/fuzz/stateful/test_targeted_stateful.py` contains target-guided variants
for distribution experiments:

- `AmmVolumeTargetStateful` constructs loans near the active band, trades with
  AMM-derived amounts from `get_amount_for_price(...)`, and targets
  `amm_volume_18` plus `active_band_move`.
- `PriceJumpTargetStateful` constructs an open loan, moves the oracle, and
  targets `oracle_jump_bps`.
- `MarketStressTargetStateful` combines AMM volume and oracle jumps to check
  whether the objectives interact as expected.
- `VaultDepositorTargetStateful` batches vault deposits toward about one hundred
  unique depositors, while also measuring depositor density per deposit step.
  The target is batch-based so it scales with the configured stateful step count
  instead of requiring one step per depositor.
- `BorrowerTargetStateful` batches loan creation toward about one hundred unique
  borrowers, while also measuring borrower density per create step. It uses the
  shared loan strategies, so high rejection here is a signal that borrower
  construction should be made more direct.

These target classes must inherit real state machines. Targeting should bias
exploration while ordinary protocol rules still run; it must not shadow inherited
rules with no-op methods to make target metrics look better. Target metrics are
not invariants and are not coverage by themselves. A target-guided run only means
something if normal events such as create, repay, borrow_more, remove_collateral,
deposit, withdraw, time_forward, and liquidation maintenance still appear where
that parent state machine provides them.

## Legacy Migration Checklist

Use the old stateful suites as a coverage checklist for the new
`tests/fuzz/stateful/` tree:

- `tests/lending/test_vault.py`: ERC4626 deposit/mint/withdraw/redeem,
  receiver and owner variants, approvals, preview/max functions, `MIN_ASSETS`,
  `DEAD_SHARES`, max supply, total assets, price-per-share, and APR invariants.
- `tests/lending/test_health_calculator_stateful.py`: health preview/calculator
  parity for create, repay, add collateral, borrow more, remove collateral, and
  liquidation paths.
- `tests/lending/test_st_interest_conservation.py`: time/rate changes, debt sum
  versus total debt, payable borrowed-token accounting, available balance, vault
  assets, and admin-fee behavior.
- `tests/lending/test_health_in_trades.py` and
  `tests/lending/test_shifted_trades.py`: adiabatic oracle moves, shifted oracle
  starts, random AMM trades, time/rate changes during trades, and borrower health
  after those sequences.
- `tests/amm/test_st_exchange.py` and `tests/amm/test_st_exchange_dy.py`:
  `exchange`, `exchange_dy`, `get_dx`, `get_dydx`, round-trip checks, AMM token
  solvency against band balances, and teardown trade-back checks.
- `tests/lending/test_bigfuzz.py`: integrated controller/vault/trade/rate/time
  scenarios, debt-cap or borrow-cap mutation, partial liquidation,
  self-liquidation, callback liquidation, and fee collection where relevant.
- LM callback integration/stateful tests: gauge checkpoints, reward accrual,
  claim flows, kill/unkill, and collateral accounting across AMM movement.

When a behavior moves into `tests/fuzz/stateful/`, add a stable `event(...)`
name. If a behavior is not migrated yet, keep it visible as a gap instead of
implying the new suite already replaces the old one.

## Agent-Assisted Tuning

Use agents to find wasted stateful-test time. Unsatisfiable strategies are
especially sneaky: the test can run for a long time and look serious while
Hypothesis is mostly rejecting examples and not exercising the protocol paths you
care about.

Ask an agent to benchmark and inspect both runtime and exploration quality. For
example:

```text
Benchmark tests/fuzz/stateful with uv. Use --hypothesis-show-statistics,
--hypothesis-verbosity=verbose, and pytest durations. Identify the slowest
stateful class, rule, invariant, or strategy. Check Hypothesis notes and events
to confirm that create, repay, borrow_more, remove_collateral, deposit, withdraw,
and liquidation paths are actually being hit. Look for excessive assume/filter
rejections or unsatisfiable draws, especially in runtime-dependent strategies.
If a test is slow because it is rejecting inputs rather than running useful
actions, make the strategy generate valid values from the start and rerun the
benchmark.
```

Prefer constructive strategies over post-generation filtering. For static
bounds, encode the protocol constraints directly in the strategy. For bounds that
depend on deployed market state, use `data()` to draw values after reading the
runtime information needed to make them satisfiable, as long as the extra runtime
work does not dominate the test.

The agent should report:

- Which stateful class is slowest.
- Whether time is spent in setup, strategy drawing, rule execution, invariants,
  or teardown.
- Which `assume(...)` or generated bounds are causing high rejection rates.
- Which `note(...)` and `event(...)` categories appeared in the run.
- Which expected behaviors did not appear at all.

Do not treat elapsed time as coverage. A long stateful run with poor Hypothesis
statistics can be worse than a short run with well-targeted strategies and
balanced events.

An agent can also use Hypothesis statistics, notes, events, and observability
output to inspect whether tests are stuck in dead branches, repeatedly rejecting
inputs, or missing important protocol paths. The point is not to enforce a
formal coverage checklist; it is to notice when a long run is not actually
exercising the behavior the state machine is supposed to explore.

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
