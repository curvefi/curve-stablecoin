#!/usr/bin/env python3
"""
Script to extract internal/external methods from Vyper contracts
and compare with test file coverage in tests/unitary/
"""

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import TypedDict


class MethodInfo(TypedDict):
    name: str
    lineno: int
    is_view: bool
    is_pure: bool


class ContractMethods(TypedDict):
    internal: list[MethodInfo]
    external: list[MethodInfo]


def get_vyper_methods(
    contract_path: Path, verbose: bool = False
) -> ContractMethods | None:
    """
    Extract internal and external methods from a Vyper contract using annotated_ast.
    Returns None if the contract uses an incompatible Vyper version.
    """
    result = subprocess.run(
        ["vyper", "-f", "annotated_ast", str(contract_path)],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        # Skip contracts with incompatible Vyper versions or other compilation issues
        skip_reasons = [
            "VersionException",
            "not compatible with compiler",
            "FunctionDeclarationException",  # Old @external def __init__ syntax
            "ModuleNotFound",  # Missing dependencies
        ]
        if any(reason in result.stderr for reason in skip_reasons):
            if verbose:
                print(f"Skipping {contract_path} (compilation issue)", file=sys.stderr)
            return None
        print(f"Error compiling {contract_path}: {result.stderr}", file=sys.stderr)
        return None

    try:
        ast_data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(f"Error parsing AST for {contract_path}: {e}", file=sys.stderr)
        return None

    internal: list[MethodInfo] = []
    external: list[MethodInfo] = []

    def extract_functions(node: dict) -> None:
        if node.get("ast_type") == "FunctionDef":
            name = node.get("name", "")
            lineno = node.get("lineno", 0)
            decorators = node.get("decorator_list", [])
            decorator_names = [d.get("id", "") for d in decorators]

            is_external = "external" in decorator_names
            is_internal = "internal" in decorator_names
            is_view = "view" in decorator_names
            is_pure = "pure" in decorator_names

            method_info: MethodInfo = {
                "name": name,
                "lineno": lineno,
                "is_view": is_view,
                "is_pure": is_pure,
            }

            if is_external:
                external.append(method_info)
            elif is_internal:
                internal.append(method_info)
            # Note: __init__ and __default__ are implicitly external but might not have decorator

        # Recursively search in body
        if "body" in node:
            for child in node.get("body", []):
                if isinstance(child, dict):
                    extract_functions(child)

    # Start from the AST root
    ast_root = ast_data.get("ast", ast_data)
    extract_functions(ast_root)

    return {"internal": internal, "external": external}


def get_all_contracts(base_path: Path) -> dict[str, Path]:
    """Get all .vy contract files, excluding testing/ and interfaces/.

    If ``base_path`` is a single contract file, return only that file.
    """
    contracts: dict[str, Path] = {}

    if base_path.is_file():
        # Allow passing a single contract file
        if base_path.suffix != ".vy":
            return contracts
        rel_path = base_path
        # Preserve subdirectories if relative to CWD
        try:
            rel_path = base_path.relative_to(Path.cwd())
        except ValueError:
            pass
        # Strip top-level "curve_stablecoin" if present to match test layout
        rel_parts = rel_path.parts
        if rel_parts and rel_parts[0] == "curve_stablecoin":
            rel_path = Path(*rel_parts[1:]) if len(rel_parts) > 1 else Path(rel_parts[0])
        # Skip constants.vy (no methods)
        if base_path.name != "constants.vy":
            contracts[str(rel_path.as_posix())] = base_path
        return contracts

    for vy_file in base_path.rglob("*.vy"):
        # Skip testing and interfaces directories
        rel_path = vy_file.relative_to(base_path)
        if rel_path.parts[0] in ("testing", "interfaces"):
            continue
        # Skip constants.vy (no methods)
        if vy_file.name == "constants.vy":
            continue
        contracts[str(rel_path)] = vy_file
    return contracts


def camel_to_snake(name: str) -> str:
    """Convert camelCase/PascalCase to snake_case."""
    # Insert underscore before uppercase letters and lowercase them
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s1).lower()


def get_expected_test_path(contract_rel_path: str) -> Path:
    """
    Convert contract path to expected test directory structure.
    e.g., "lending/LendController.vy" -> "lending/lend_controller/"
    """
    parts = Path(contract_rel_path).parts
    # Remove .vy extension and convert PascalCase to snake_case
    contract_name = parts[-1].replace(".vy", "")
    contract_name = camel_to_snake(contract_name)
    # Build test path (relative to tests/unitary)
    if len(parts) > 1:
        subdir = "/".join(parts[:-1])
        return Path(f"{subdir}/{contract_name}")
    return Path(contract_name)


def normalize_method_name(method_name: str) -> str:
    """Normalize method name for test file matching.

    - __init__ -> init (constructor alias used elsewhere)
    - Strip leading underscores
    - Convert camelCase to snake_case
    """
    if method_name == "__init__":
        return "init"
    if method_name == "__default__":
        return "default"
    normalized = method_name.lstrip("_")
    normalized = camel_to_snake(normalized)
    return normalized.rstrip("_")


def method_matches_test_file(
    method_name: str, test_filename: str, is_internal: bool
) -> bool:
    """Check if a test file matches a method, allowing prefixes/suffixes.

    Matches:
      - test_<method>.py
      - test_<prefix>_<method>.py (prefix helps disambiguate across contracts)
      - test_<method>_*.py or test_<prefix>_<method>_*.py (suffix variants)
      - For internal: test_internal_<...> equivalents
      - For __init__: also accept "ctor" alias
    """
    import re

    normalized_method = normalize_method_name(method_name)
    aliases = [normalized_method]
    if normalized_method == "init":
        aliases.append("ctor")

    test_name = test_filename.removesuffix(".py")

    # Build regex to allow optional prefix and suffix (suffix helps disambiguate contracts)
    suffix_pattern = r"(?:_[a-z0-9]+)*"
    if is_internal:
        patterns = [rf"^test_internal_(?:[a-z0-9_]+_)?{re.escape(alias)}{suffix_pattern}$" for alias in aliases]
    else:
        patterns = [rf"^test_(?:[a-z0-9_]+_)?{re.escape(alias)}{suffix_pattern}$" for alias in aliases]

    return any(re.match(pat, test_name) for pat in patterns)


def find_matching_test(
    method_name: str, existing_tests: set[str], is_internal: bool
) -> str | None:
    """Find a test file that matches the method, or return None.

    Prefer exact filename matches (test_<method>.py) before prefix matches
    (e.g. test_<method>_v.py) to avoid misattributing similar method names.
    """
    normalized = normalize_method_name(method_name)
    expected = f"test_{normalized}.py" if not is_internal else f"test_internal_{normalized}.py"

    # Exact match first
    if expected in existing_tests:
        return expected

    # Prefix matches (e.g. test_method_v.py)
    for test_file in sorted(existing_tests):
        if method_matches_test_file(method_name, test_file, is_internal):
            return test_file
    return None


def check_test_coverage(
    contracts_path: Path, tests_path: Path, verbose: bool = False
) -> dict[str, dict]:
    """Check which methods have test files."""
    contracts = get_all_contracts(contracts_path)
    coverage_report = {}

    for rel_path, contract_file in sorted(contracts.items()):
        methods = get_vyper_methods(contract_file, verbose=verbose)
        if methods is None:
            # Skip incompatible contracts
            continue
        # Preserve nested paths when a single file is passed (rel_path may already include subdirs)
        expected_test_dir = tests_path / get_expected_test_path(rel_path)

        # Get existing test files
        existing_tests = set()
        if expected_test_dir.exists():
            existing_tests = {f.name for f in expected_test_dir.glob("test_*.py")}

        missing_internal = []
        missing_external = []
        covered_internal = []
        covered_external = []

        for method in methods["internal"]:
            matched_test = find_matching_test(
                method["name"], existing_tests, is_internal=True
            )
            if matched_test:
                covered_internal.append(method["name"])
            else:
                missing_internal.append(method["name"])

        for method in methods["external"]:
            matched_test = find_matching_test(
                method["name"], existing_tests, is_internal=False
            )
            if matched_test:
                covered_external.append(method["name"])
            else:
                missing_external.append(method["name"])

        # Find extraneous test files that don't match any method
        matched_test_files = set()
        for method in methods["internal"]:
            matched = find_matching_test(
                method["name"], existing_tests, is_internal=True
            )
            if matched:
                matched_test_files.add(matched)
        for method in methods["external"]:
            matched = find_matching_test(
                method["name"], existing_tests, is_internal=False
            )
            if matched:
                matched_test_files.add(matched)

        extraneous_tests = sorted(existing_tests - matched_test_files)

        coverage_report[rel_path] = {
            "methods": methods,
            "expected_test_dir": str(expected_test_dir),
            "existing_tests": sorted(existing_tests),
            "missing": {
                "internal": missing_internal,
                "external": missing_external,
            },
            "covered": {
                "internal": covered_internal,
                "external": covered_external,
            },
            "extraneous": extraneous_tests,
        }

    return coverage_report


def print_methods_dict(contract_path: Path) -> None:
    """Print the internal/external methods dict for a single contract."""
    methods = get_vyper_methods(contract_path, verbose=True)
    if methods is None:
        print("{}", file=sys.stderr)
        return
    print(json.dumps(methods, indent=2))


def generate_test_file_content(
    contract_name: str, method_name: str, is_internal: bool
) -> str:
    """Generate content for a scaffolded test file."""
    method_type = "internal" if is_internal else "external"

    return f'''"""Tests for {contract_name}.{method_name} ({method_type})"""

import pytest


@pytest.mark.skip(reason="Not implemented")
def test_default_behavior():
    """Test default behavior of {method_name}."""
    pass
'''


def scaffold_missing_tests(
    contracts_path: Path, tests_path: Path, verbose: bool = False, dry_run: bool = False
) -> int:
    """Create missing test files. Returns the number of files created."""
    report = check_test_coverage(contracts_path, tests_path, verbose=verbose)
    files_created = 0

    for contract, data in sorted(report.items()):
        missing = data["missing"]
        if not missing["internal"] and not missing["external"]:
            continue

        test_dir = Path(data["expected_test_dir"])
        contract_name = Path(contract).stem  # e.g., "Controller" from "Controller.vy"

        # Create directory if needed
        if not dry_run and (missing["internal"] or missing["external"]):
            test_dir.mkdir(parents=True, exist_ok=True)

        # Create missing external test files
        for method in missing["external"]:
            normalized = normalize_method_name(method)
            test_file = test_dir / f"test_{normalized}.py"
            if dry_run:
                print(f"Would create: {test_file}")
            else:
                content = generate_test_file_content(
                    contract_name, method, is_internal=False
                )
                test_file.write_text(content)
                print(f"Created: {test_file}")
            files_created += 1

        # Create missing internal test files
        for method in missing["internal"]:
            normalized = normalize_method_name(method)
            test_file = test_dir / f"test_internal_{normalized}.py"
            if dry_run:
                print(f"Would create: {test_file}")
            else:
                content = generate_test_file_content(
                    contract_name, method, is_internal=True
                )
                test_file.write_text(content)
                print(f"Created: {test_file}")
            files_created += 1

    return files_created


def check_coverage_strict(
    contracts_path: Path, tests_path: Path, verbose: bool = False
) -> bool:
    """Check coverage and return True if all methods have tests, False otherwise."""
    report = check_test_coverage(contracts_path, tests_path, verbose=verbose)

    missing_count = 0
    extraneous_count = 0
    for contract, data in report.items():
        missing = data["missing"]
        missing_count += len(missing["internal"]) + len(missing["external"])
        extraneous_count += len(data.get("extraneous", []))

    has_errors = missing_count > 0 or extraneous_count > 0

    if has_errors:
        print_coverage_report(report)
        if missing_count > 0:
            print(f"\nError: {missing_count} methods are missing test files.")
            print(
                "Run 'python scripts/vyper_method_checker.py scaffold' to create them."
            )
        if extraneous_count > 0:
            print(f"\nError: {extraneous_count} test files don't match any method.")
        return False

    print("All methods have test files.")
    return True


def print_coverage_report(report: dict[str, dict]) -> None:
    """Print a human-readable coverage report."""
    total_external = 0
    total_internal = 0
    covered_external = 0
    covered_internal = 0
    total_extraneous = 0

    for contract, data in report.items():
        methods = data["methods"]
        missing = data["missing"]
        extraneous = data.get("extraneous", [])

        n_ext = len(methods["external"])
        n_int = len(methods["internal"])
        n_ext_covered = len(data["covered"]["external"])
        n_int_covered = len(data["covered"]["internal"])

        total_external += n_ext
        total_internal += n_int
        covered_external += n_ext_covered
        covered_internal += n_int_covered
        total_extraneous += len(extraneous)

        has_issues = missing["internal"] or missing["external"] or extraneous

        if has_issues:
            print(f"\n{'=' * 60}")
            print(f"📄 {contract}")
            print(f"   Expected test dir: {data['expected_test_dir']}")
            print(f"   External: {n_ext_covered}/{n_ext} covered")
            print(f"   Internal: {n_int_covered}/{n_int} covered")

            if missing["external"]:
                print("\n   Missing external tests:")
                for m in sorted(missing["external"]):
                    normalized = normalize_method_name(m)
                    print(f"      - test_{normalized}.py")

            if missing["internal"]:
                print("\n   Missing internal tests:")
                for m in sorted(missing["internal"]):
                    normalized = normalize_method_name(m)
                    print(f"      - test_internal_{normalized}.py")

            if data.get("extraneous"):
                print("\n   Extraneous tests (don't match any method):")
                for t in data["extraneous"]:
                    print(f"      - {t}")

    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    print(
        f"External methods: {covered_external}/{total_external} covered ({100 * covered_external / total_external:.1f}%)"
        if total_external
        else "External methods: 0/0"
    )
    print(
        f"Internal methods: {covered_internal}/{total_internal} covered ({100 * covered_internal / total_internal:.1f}%)"
        if total_internal
        else "Internal methods: 0/0"
    )
    if total_extraneous:
        print(f"Extraneous test files: {total_extraneous}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract Vyper contract methods and check test coverage"
    )
    parser.add_argument(
        "command",
        choices=["methods", "coverage", "json", "scaffold", "check"],
        help=(
            "Command to run: "
            "'methods' for single contract, "
            "'coverage' for full report, "
            "'json' for JSON output, "
            "'scaffold' to create missing test files, "
            "'check' for CI (exits with error if missing tests)"
        ),
    )
    parser.add_argument(
        "path",
        nargs="?",
        help="Path to contract file (for 'methods') or contracts directory (for others)",
    )
    parser.add_argument(
        "--tests-dir",
        default="tests/unitary",
        help="Path to tests directory (default: tests/unitary)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show skipped contracts (incompatible Vyper versions)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="For 'scaffold': show what would be created without creating files",
    )

    args = parser.parse_args()

    if args.command == "methods":
        if not args.path:
            print(
                "Error: path to contract file required for 'methods' command",
                file=sys.stderr,
            )
            sys.exit(1)
        contract_path = Path(args.path)
        if not contract_path.exists():
            print(f"Error: {contract_path} does not exist", file=sys.stderr)
            sys.exit(1)
        print_methods_dict(contract_path)

    elif args.command in ("coverage", "json"):
        contracts_path = Path(args.path) if args.path else Path("curve_stablecoin")
        tests_path = Path(args.tests_dir)

        if not contracts_path.exists():
            print(f"Error: {contracts_path} does not exist", file=sys.stderr)
            sys.exit(1)

        report = check_test_coverage(contracts_path, tests_path, verbose=args.verbose)

        if args.command == "json":
            # For JSON output, simplify the methods structure
            json_report = {}
            for contract, data in report.items():
                json_report[contract] = {
                    "internal": [m["name"] for m in data["methods"]["internal"]],
                    "external": [m["name"] for m in data["methods"]["external"]],
                    "expected_test_dir": data["expected_test_dir"],
                    "missing_tests": data["missing"],
                    "covered_tests": data["covered"],
                    "extraneous_tests": data.get("extraneous", []),
                }
            print(json.dumps(json_report, indent=2))
        else:
            print_coverage_report(report)

    elif args.command == "scaffold":
        contracts_path = Path(args.path) if args.path else Path("curve_stablecoin")
        tests_path = Path(args.tests_dir)

        if not contracts_path.exists():
            print(f"Error: {contracts_path} does not exist", file=sys.stderr)
            sys.exit(1)

        files_created = scaffold_missing_tests(
            contracts_path, tests_path, verbose=args.verbose, dry_run=args.dry_run
        )
        if args.dry_run:
            print(f"\nWould create {files_created} test files.")
        else:
            print(f"\nCreated {files_created} test files.")

    elif args.command == "check":
        contracts_path = Path(args.path) if args.path else Path("curve_stablecoin")
        tests_path = Path(args.tests_dir)

        if not contracts_path.exists():
            print(f"Error: {contracts_path} does not exist", file=sys.stderr)
            sys.exit(1)

        success = check_coverage_strict(
            contracts_path, tests_path, verbose=args.verbose
        )
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
