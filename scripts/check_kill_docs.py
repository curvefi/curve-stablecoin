#!/usr/bin/env python3
"""Pre-commit hook to verify Vyper contracts have @custom:kill documentation."""

import json
import subprocess
import sys
from pathlib import Path


def is_contract(filepath: str) -> bool:
    """
    Determine if a file is a deployable contract based on naming convention.

    CamelCase filenames are contracts and need @custom:kill.
    snake_case filenames are libraries and are skipped.
    """
    filename = Path(filepath).stem
    # A file is a contract if its first character is uppercase (CamelCase)
    return filename[0].isupper()


def check_file(filepath: str) -> bool:
    """Check if a Vyper file has @custom:kill in its devdoc."""
    try:
        result = subprocess.run(
            ["vyper", "-f", "devdoc", filepath],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            # Compilation failed, skip this file
            return True

        devdoc = json.loads(result.stdout)
        return "custom:kill" in devdoc

    except (json.JSONDecodeError, FileNotFoundError):
        return True


def main() -> int:
    failed_files = []

    for filepath in sys.argv[1:]:
        if is_contract(filepath) and not check_file(filepath):
            failed_files.append(filepath)

    if failed_files:
        print("Missing @custom:kill documentation in:")
        for f in failed_files:
            print(f"  - {f}")
        print("\nAdd a '@custom:kill' attribute explaining how to kill the contract.")
        print("See STYLE.md for naming conventions.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
