# Style Guide

## File Naming Conventions

### Vyper Files

- **CamelCase** (e.g., `LendFactory.vy`, `Controller.vy`): Deployable contracts
- **snake_case** (e.g., `blueprint_registry.vy`, `constants.vy`): Libraries and modules

This naming convention determines whether a file is treated as a compilation target:

| Naming | Type | Example | Requires `@custom:kill` |
|--------|------|---------|------------------------|
| CamelCase | Contract | `LendFactory.vy` | Yes |
| snake_case | Library | `blueprint_registry.vy` | No |

### Python Files

- **snake_case** for all Python files (e.g., `constants.py`, `deployers.py`)

## Test Fixtures

The shared `accounts` pytest fixture is deprecated and should not be used in new tests.

`accounts` is a pattern borrowed from other testing frameworks. It is not idiomatic `titanoboa`, and we do not want to carry that style forward here.

Why:

- It hides actor intent behind positional indexing like `accounts[0]` and `accounts[1]`.
- It severs the semantic link between the address and the permission or role being tested.
- It forces readers to infer meaning from surrounding setup instead of getting it directly from the variable name.
- It makes tests harder to read, review, and maintain because roles are implicit instead of named.

Prefer inline role-named addresses such as `non_owner`, `liquidator`, `fee_receiver`, `borrower`, `keeper`, or other test-specific actor names that make permissions and intent obvious.

Example:

```python
non_owner = boa.env.generate_address("non_owner")
liquidator = boa.env.generate_address("liquidator")
```

## Contract Documentation

All deployable contracts (CamelCase `.vy` files) must include a `@custom:kill` attribute in their module docstring explaining how to disable or kill the contract:

```vyper
"""
@title My Contract
@author Curve.fi
@custom:kill Describe how to kill/disable this contract
"""
```
