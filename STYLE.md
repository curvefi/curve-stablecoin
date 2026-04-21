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

Deprecated pytest address fixtures like `accounts`, `alice`, `bob`, and `charlie` should not be used in new tests. The same names should also not be used for inline addresses or `boa.env.generate_address(...)` labels.

`accounts` is a pattern borrowed from other testing frameworks, and single-name actor fixtures like `alice` and `bob` have the same readability problem in practice. They are not idiomatic `titanoboa`, and we do not want to carry that style forward here.

Why:

- It hides actor intent behind positional indexing like `accounts[0]` and `accounts[1]`.
- It uses generic actor names like `alice` or `bob`, whether via fixtures or inline addresses, that still force readers to translate names into roles.
- It severs the semantic link between the address and the permission or role being tested.
- It forces readers to infer meaning from surrounding setup instead of getting it directly from the variable name.
- It makes tests harder to read, review, and maintain because roles are implicit instead of named.

Prefer inline role-named addresses such as `depositor`, `admin`, `victim`, `attacker`, `non_owner`, `liquidator`, `fee_receiver`, `borrower`, `keeper`, or other test-specific actor names that make permissions and intent obvious.

Example:

```python
non_owner = boa.env.generate_address("non_owner")
liquidator = boa.env.generate_address("liquidator")

# Avoid generic names like these:
# alice = boa.env.generate_address("alice")
# bob = boa.env.generate_address("bob")
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
