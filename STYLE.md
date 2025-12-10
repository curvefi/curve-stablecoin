# Style Guide

## File Naming Conventions

### Vyper Files

- **CamelCase** (e.g., `LendFactory.vy`, `Controller.vy`): Deployable contracts
- **ICamelCase** (e.g., `IMintMonetaryPolicy.vyi`, `IController.vyi`): Interfaces
- **snake_case** (e.g., `blueprint_registry.vy`, `constants.vy`): Libraries and modules

This naming convention determines whether a file is treated as a compilation target:

| Naming | Type | Example | Requires `@custom:kill` |
|--------|------|---------|------------------------|
| CamelCase | Contract | `LendFactory.vy` | Yes |
| ICamelCase | Interface | `IController.vyi` | No |
| snake_case | Library | `blueprint_registry.vy` | No |

### Python Files

- **snake_case** for all Python files (e.g., `constants.py`, `deployers.py`)

## Contract Documentation

All deployable contracts (CamelCase `.vy` files) must include a `@custom:kill` attribute in their module docstring explaining how to disable or kill the contract:

```vyper
"""
@title My Contract
@author Curve.fi
@custom:kill Describe how to kill/disable this contract
"""
```
