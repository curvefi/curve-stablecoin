#!/usr/bin/env python3
"""
AST-driven test scaffolder for Vyper contracts.

Features:
- Reads annotated_ast from vyper and walks function bodies
- Generates stub tests for each function, adding one test per branch (if/elif/else)
- Generates revert-focused stubs for asserts/raises
- Adds comments to remind checking events when logs are detected

Usage:
    python scripts/vyper_ast_scaffolder.py scaffold <contract.vy> --tests-dir tests/unitary [--dry-run]

Test naming follows the coverage script conventions, adding a short contract suffix
(e.g. lend_controller -> lc) to disambiguate files:
- Constructor: test_ctor_<suffix>.py
- External: test_<method>_<suffix>.py
- Internal: test_internal_<method>_<suffix>.py
Within each file, multiple test_... functions are scaffolded for branches and reverts.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

TEMPLATE_README = Path(__file__).resolve().parent / "templates" / "scaffold_readme.md"

# -------- helpers duplicated from vyper_method_checker --------


def camel_to_snake(name: str) -> str:
    import re

    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s1).lower()


def normalize_method_name(method_name: str) -> str:
    if method_name == "__init__":
        return "init"
    if method_name == "__default__":
        return "default"
    stripped = method_name.lstrip("_")
    normalized = camel_to_snake(stripped).rstrip("_")
    return normalized


def get_expected_test_path(contract_rel_path: str) -> Path:
    parts = Path(contract_rel_path).parts
    contract_name = camel_to_snake(parts[-1].replace(".vy", ""))
    if len(parts) > 1:
        subdir = "/".join(parts[:-1])
        return Path(f"{subdir}/{contract_name}")
    return Path(contract_name)


def compute_contract_suffix(contract_snake: str) -> str:
    parts: list[str] = []
    for chunk in contract_snake.split("_"):
        if not chunk:
            continue
        letters = "".join(ch for ch in chunk if ch.isalpha())
        digits = "".join(ch for ch in chunk if ch.isdigit())
        if letters:
            parts.append(letters[0] + digits)
        elif digits:
            parts.append(digits)
    suffix = "".join(parts)
    return suffix or contract_snake[:3]

# -------------------------------------------------------------


def write_readme(test_root: Path, dry_run: bool = False) -> None:
    if not TEMPLATE_README.exists():
        return
    target = test_root / "README.md"
    if dry_run:
        print(f"Would write README template to {target}")
        return
    content = TEMPLATE_README.read_text()
    target.write_text(content)
    print(f"Wrote README template to {target}")


def load_ast(contract_path: Path) -> Dict[str, Any]:
    result = subprocess.run(
        ["vyper", "-f", "annotated_ast", str(contract_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"vyper failed for {contract_path}: {result.stderr}")
    return json.loads(result.stdout)


def extract_functions(ast_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    funcs: List[Dict[str, Any]] = []

    def walk(node: Dict[str, Any]):
        if node.get("ast_type") == "FunctionDef":
            funcs.append(node)
        for child in node.get("body", []) or []:
            if isinstance(child, dict):
                walk(child)

    root = ast_data.get("ast", ast_data)
    walk(root)
    return funcs


def get_source_lines(path: Path) -> List[str]:
    return path.read_text().splitlines()


def describe_line(src_lines: List[str], lineno: int) -> str:
    if 1 <= lineno <= len(src_lines):
        return src_lines[lineno - 1].strip()
    return ""


def collect_branches(fn: Dict[str, Any], src_lines: List[str], start_line: int, end_line: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    import re

    branches: List[Dict[str, Any]] = []
    reverts: List[Dict[str, Any]] = []
    logs: List[Dict[str, Any]] = []
    storage_updates: List[Dict[str, Any]] = []
    seen_log_lines: set[int] = set()
    seen_storage: set[tuple[int, str]] = set()

    def extract_self_var(target: Dict[str, Any]) -> str | None:
        if not isinstance(target, dict):
            return None
        ast_type = target.get("ast_type")
        if ast_type == "Attribute":
            val = target.get("value")
            if isinstance(val, dict) and val.get("id") == "self":
                return target.get("attr") or target.get("id") or target.get("attrname")
        if ast_type == "Subscript":
            return extract_self_var(target.get("value", {}))
        return None

    def record_storage(line: int, text: str, var: str):
        key = (line, var)
        if key not in seen_storage:
            storage_updates.append({"lineno": line, "desc": text, "var": var})
            seen_storage.add(key)

    def walk(node: Dict[str, Any]):
        ast_type = node.get("ast_type")
        line = node.get("lineno", 0)
        text = describe_line(src_lines, line)

        # Heuristic for logs: capture any line containing a `log` statement
        if line and line not in seen_log_lines and text and re.search(r"\blog\b", text):
            logs.append({"lineno": line, "desc": text})
            seen_log_lines.add(line)

        # Storage writes: only when assignment targets self.<var>
        found_storage = False
        if ast_type == "Assign":
            for tgt in node.get("targets", []) or []:
                var = extract_self_var(tgt)
                if var:
                    record_storage(line, text, var)
                    found_storage = True
        elif ast_type in {"AugAssign", "AnnAssign"}:
            var = extract_self_var(node.get("target", {}))
            if var:
                record_storage(line, text, var)
                found_storage = True

        # Fallback heuristic: self.<var> assignment on the line (avoid ==)
        if not found_storage and text:
            match = re.match(r"\s*self\.([A-Za-z_][A-Za-z0-9_]*)(?:\[[^\]]+\])?\s*(?:[+\-*/%])?=", text)
            if match:
                record_storage(line, text, match.group(1))

        if ast_type == "If":
            branches.append({"lineno": line, "desc": describe_line(src_lines, line)})
            # else/elif tracked via orelse marker
            if node.get("orelse"):
                else_line = node.get("orelse", [{}])[0].get("lineno", line)
                branches.append({"lineno": else_line, "desc": f"else at line {else_line}: {describe_line(src_lines, else_line)}"})
        elif ast_type == "Assert":
            reverts.append({"lineno": line, "desc": describe_line(src_lines, line)})
        elif ast_type == "Raise":
            reverts.append({"lineno": line, "desc": describe_line(src_lines, line)})

        for child in node.get("body", []) or []:
            if isinstance(child, dict):
                walk(child)
        for child in node.get("orelse", []) or []:
            if isinstance(child, dict):
                walk(child)

    walk(fn)

    # Text scan fallback within function body to catch any missed self.<var> assignments
    for lineno in range(start_line, end_line):
        text = describe_line(src_lines, lineno)
        if not text:
            continue
        match = re.match(r"\s*self\.([A-Za-z_][A-Za-z0-9_]*)(?:\[[^\]]+\])?\s*(?:[+\-*/%])?=", text)
        if match:
            record_storage(lineno, text, match.group(1))

    return branches, reverts, logs, storage_updates


def scaffold_function(contract_name: str, method_name: str, is_internal: bool, branches, reverts, logs, storage_updates) -> str:
    method_type = "internal" if is_internal else "external"
    header = (
        f'"""Tests for {contract_name}.{method_name} ({method_type})"""\n'
        "# Scaffold for LLM-aided unit tests; rename generic branch/revert names to human-readable cases.\n"
        "# Generic placeholders like test_default_behavior_branch_1 or test_revert_1 should be renamed meaningfully; keep the test_default_behavior prefix, only change the suffix.\n\n"
        "import pytest\n\n"
    )
    lines = [header]

    def combine_comments(*parts: str | None) -> str | None:
        joined = "\n".join(p for p in parts if p)
        return joined or None

    def add_test(name: str, doc: str, extra_comment: str | None = None):
        lines.append("@pytest.mark.skip(reason=\"Not implemented\")")
        lines.append(f"def {name}():")
        lines.append(f"    \"\"\"{doc}\"\"\"")
        if extra_comment:
            for comment_line in extra_comment.split("\n"):
                lines.append(f"    # {comment_line}")
        lines.append("    pass\n")

    log_comment = None
    if logs:
        import re

        def format_log_hint(log: Dict[str, Any]) -> str:
            desc = log.get("desc", "").strip()
            lineno = log.get("lineno")
            event = None
            # Capture final identifier after optional namespace like `log Interface.Event`
            match = re.search(r"log\s+(?:[A-Za-z_][A-Za-z0-9_]*\.)?([A-Za-z_][A-Za-z0-9_]*)", desc)
            if match:
                event = match.group(1)
            base = f"Expected event/log at line {lineno}: {desc}"
            if event:
                return f"{base}; use tests.utils.filter_logs(contract, \"{event}\")"
            return f"{base}; use tests.utils.filter_logs(contract, <event_name>)"

        log_comment = "\n".join(format_log_hint(log) for log in logs)

    storage_comment = None
    if storage_updates:
        hints = []
        for upd in storage_updates:
            lineno = upd.get("lineno")
            desc = upd.get("desc", "").strip()
            var = upd.get("var", "<var>")
            hints.append(
                f"Verify self.{var} updated at line {lineno}: {desc}; prefer public getter, else contract.eval(\"self.{var}\")"
            )
        storage_comment = "\n".join(hints)

    default_comment = combine_comments(storage_comment, log_comment)

    # Always include a default behavior path (no branching taken)
    add_test("test_default_behavior", "Default behavior (path without branching)", extra_comment=default_comment)

    # Branch tests (attach hints if available)
    branch_comment = combine_comments(storage_comment, log_comment)
    for idx, br in enumerate(branches):
        doc = f"Branch at line {br.get('lineno')}: {br.get('desc','').strip()}"
        add_test(f"test_default_behavior_branch_{idx+1}", doc, extra_comment=branch_comment)

    # Revert paths (only revert hint; logs and storage writes do not occur on revert paths)
    for idx, rv in enumerate(reverts):
        doc = f"Revert path at line {rv.get('lineno')}: {rv.get('desc','').strip()}"
        extra = "Use boa.reverts() to assert failure"
        add_test(f"test_revert_{idx+1}", doc, extra_comment=extra)

    return "\n".join(lines).rstrip() + "\n"


def scaffold_contract(contract_path: Path, tests_dir: Path, dry_run: bool = False) -> int:
    ast_data = load_ast(contract_path)
    functions = sorted(extract_functions(ast_data), key=lambda fn: fn.get("lineno", 0))
    src_lines = get_source_lines(contract_path)

    rel_path = contract_path
    try:
        rel_path = contract_path.relative_to(Path.cwd())
    except ValueError:
        pass
    if rel_path.parts and rel_path.parts[0] == "curve_stablecoin":
        rel_path = Path(*rel_path.parts[1:])

    contract_snake = normalize_method_name(rel_path.stem)
    contract_suffix = compute_contract_suffix(contract_snake)
    test_root = tests_dir / get_expected_test_path(rel_path.as_posix())
    test_root.mkdir(parents=True, exist_ok=True)

    write_readme(test_root, dry_run=dry_run)

    created = 0
    for idx, fn in enumerate(functions):
        decorators = [d.get("id", "") for d in fn.get("decorator_list", [])]
        is_external = "external" in decorators or fn.get("name") in {"__init__", "__default__"}
        is_internal = "internal" in decorators
        method_name = fn.get("name", "")
        normalized = normalize_method_name(method_name)
        method_alias = "ctor" if method_name == "__init__" else normalized

        base_name = method_alias if not contract_suffix else f"{method_alias}_{contract_suffix}"

        filename = (
            f"test_{base_name}.py" if is_external else f"test_internal_{base_name}.py"
        )
        target_file = test_root / filename

        start_line = fn.get("lineno", 0) or 1
        next_start = functions[idx + 1].get("lineno", len(src_lines) + 1) if idx + 1 < len(functions) else len(src_lines) + 1
        branches, reverts, logs, storage_updates = collect_branches(fn, src_lines, start_line, next_start)
        content = scaffold_function(rel_path.stem, method_name, is_internal, branches, reverts, logs, storage_updates)

        if dry_run:
            print(f"Would create/overwrite {target_file}")
            continue
        target_file.write_text(content)
        created += 1
        print(f"Created scaffold: {target_file}")

    return created


def main():
    parser = argparse.ArgumentParser(description="AST-driven Vyper test scaffolder")
    parser.add_argument("command", choices=["scaffold"], help="Action to perform")
    parser.add_argument("contract", help="Path to Vyper contract")
    parser.add_argument("--tests-dir", default="tests/unitary", help="Tests root directory")
    parser.add_argument("--dry-run", action="store_true", help="List actions without writing files")
    args = parser.parse_args()

    contract_path = Path(args.contract)
    if not contract_path.exists():
        print(f"Contract not found: {contract_path}", file=sys.stderr)
        sys.exit(1)

    if args.command == "scaffold":
        created = scaffold_contract(contract_path, Path(args.tests_dir), dry_run=args.dry_run)
        if args.dry_run:
            print(f"Would create {created} files (dry run)")
        else:
            print(f"Created {created} files")


if __name__ == "__main__":
    main()
