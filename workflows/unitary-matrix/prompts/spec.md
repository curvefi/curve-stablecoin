# Test Matrix Specification

These conventions are non-negotiable. Do not follow local patterns unless explicitly instructed.

## Test function naming

- Happy paths: `test_default_behavior_*`
- Reverts: `test_revert_*`
- Single case: `test_default_behavior` (no extra suffix).

## Addresses

- Inline role-named only: `boa.env.generate_address("non_owner")`.
- Never use `alice`, `bob`, `accounts`, or anonymous address fixtures.
- Step descriptions must reference role names, not generic identities.

## Reverts

- Match exact revert strings from the contract source.
- String reasons: `boa.reverts("ownable: caller is not the owner")`
- Dev reasons: `boa.reverts(dev="price oracle returned zero")`
- If a Vyper `assert` has no reason string, note that a `# dev: ...` comment needs to be added to the contract (this is the only allowed contract change).

## Events

- Verify events using `filter_logs` from `tests.utils`.
- Call `filter_logs` immediately after the emitting call with no intervening calls.
- Each event test must assert event field values, not just count.

## Constants

- Include required constants in planned test steps (for example `MAX_SKIP_TICKS`) whenever branch logic depends on them.
- For this matrix phase, do not over-specify import/source mechanics for constants; exact import style is validated in code-review phase.

## Test isolation

- Assume each pytest test function runs in isolation with fresh fixture state by default.
- Do not add boilerplate steps like "start from a fresh instance" unless a specific fixture in this suite is known to be non-function-scoped.
- Prefer branch-specific setup/actions only; avoid generic reset/setup noise.

## Per-test status classification

Each test case has its own status:
- `absent`: this test does not exist yet. Plan it.
- `compliant`: this test exists and follows all conventions.
- `non_compliant`: this test exists but violates conventions. Fill `issues` with what is wrong and how to fix it.
- `redundant`: this test exists but is redundant and does not cover a unique branch. Mark for deletion with the reason in `issues`.

## Branch justification

- Every test case must be justified by a specific code branch or condition in the function.
- The `branchName` field describes which branch or condition this test exercises.
- Do not create tests that cover the same branch with different values unless they hit different `if` or `assert` paths.
- If an existing test is redundant because another test already covers that branch, mark it `redundant`.
