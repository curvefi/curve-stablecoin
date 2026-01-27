#!/usr/bin/env python3
import argparse
import csv
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def parse_functions(source_lines: list[str]) -> list[dict]:
    funcs = []
    interface_indent = None

    for i, line in enumerate(source_lines):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))

        if stripped.startswith("interface ") and stripped.endswith(":"):
            interface_indent = indent
            continue
        if interface_indent is not None and stripped and indent <= interface_indent:
            interface_indent = None

        m = re.match(r"(\s*)def\s+(\w+)\s*\(", line)
        if m:
            if interface_indent is not None and indent > interface_indent:
                continue
            name = m.group(2)
            if name == "__init__":
                continue
            funcs.append({"name": name, "start": i, "indent": indent})

    for func in funcs:
        start = func["start"]
        indent = func["indent"]
        paren = source_lines[start].count("(") - source_lines[start].count(")")
        sig_end = start
        while True:
            line = source_lines[sig_end]
            if sig_end > start:
                paren += line.count("(") - line.count(")")
            line_no_comment = line.split("#", 1)[0].rstrip()
            if paren <= 0 and line_no_comment.endswith(":"):
                break
            sig_end += 1
            if sig_end >= len(source_lines):
                break
        func["sig_end"] = sig_end

        sig_text = " ".join(
            l.split("#", 1)[0] for l in source_lines[start : sig_end + 1]
        )
        m_ret = re.search(r"->\s*([^:]+)\s*:", sig_text)
        func["ret_type"] = m_ret.group(1).strip() if m_ret else None

        body_start = sig_end + 1
        func["body_start"] = body_start

        end = len(source_lines)
        for j in range(body_start, len(source_lines)):
            line = source_lines[j]
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            line_indent = len(line) - len(line.lstrip(" "))
            if line_indent <= indent:
                end = j
                break
        func["end"] = end

    return funcs


def dummy_return(ret_type: str | None) -> str:
    if not ret_type:
        return "return"
    if ret_type.startswith("(") and ret_type.endswith(")"):
        inner = ret_type[1:-1].strip()
        parts = [p.strip() for p in inner.split(",") if p.strip()]
        vals = []
        for p in parts:
            if (
                "[" in p
                or p.startswith("DynArray")
                or p.startswith("Bytes")
                or p.startswith("String")
            ):
                vals.append(f"empty({p})")
            elif p.startswith("uint") or p.startswith("int"):
                vals.append("0")
            elif p == "bool":
                vals.append("False")
            elif p == "address":
                vals.append("empty(address)")
            else:
                vals.append(f"empty({p})")
        return "return (" + ", ".join(vals) + ")"
    if (
        "[" in ret_type
        or ret_type.startswith("DynArray")
        or ret_type.startswith("Bytes")
        or ret_type.startswith("String")
    ):
        return f"return empty({ret_type})"
    if ret_type.startswith("uint") or ret_type.startswith("int"):
        return "return 0"
    if ret_type == "bool":
        return "return False"
    if ret_type == "address":
        return "return empty(address)"
    return f"return empty({ret_type})"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Estimate runtime bytespace per function using dummy bodies."
    )
    parser.add_argument(
        "--source",
        default="curve_stablecoin/controller.vy",
        help="Contract source file path relative to repo root.",
    )
    parser.add_argument(
        "--output-dir",
        default=".tmp/runtime-run",
        help="Output directory for runtime bytespace reports.",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=0,
        help="Parallel workers for function analysis (0 = CPU count).",
    )
    args = parser.parse_args()

    repo = Path(".")
    source_path = repo / args.source
    runtime_root = repo / args.output_dir

    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")
    runtime_dir = runtime_root / "contracts"
    results_dir = runtime_root / "results"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    source_lines = source_path.read_text().splitlines()
    funcs = parse_functions(source_lines)

    base_out = subprocess.check_output(
        ["vyper", "-f", "bytecode_runtime", str(source_path)], text=True
    )
    base_size = len(base_out.encode())

    def compile_function(func: dict) -> tuple[str, int | None, int | None]:
        name = func["name"]
        ret_type = func["ret_type"]
        dummy = dummy_return(ret_type)
        indent = func["indent"] + 4
        dummy_line = " " * indent + dummy
        body_start = func["body_start"]
        end = func["end"]

        new_lines = list(source_lines)
        new_lines[body_start:end] = [dummy_line]
        tmp_path = runtime_dir / f"{source_path.stem}-{name}.vy"
        tmp_path.write_text("\n".join(new_lines) + "\n")

        result_path = results_dir / f"{name}.md"
        try:
            out = subprocess.check_output(
                ["vyper", "-f", "bytecode_runtime", str(tmp_path)], text=True
            )
            size = len(out.encode())
            savings = base_size - size
            result_path.write_text(
                f"# {name} runtime bytespace\n\n"
                f"- Base size: {base_size} bytes\n"
                f"- New size: {size} bytes\n"
                f"- Savings: {savings} bytes\n"
                f"- Status: success\n"
            )
            return (name, size, savings)
        except subprocess.CalledProcessError as exc:
            result_path.write_text(
                f"# {name} runtime bytespace\n\n"
                f"- Base size: {base_size} bytes\n"
                f"- Status: failed\n"
                f"- Error: {exc}\n"
            )
            return (name, None, None)

    results = []
    worker_count = args.jobs if args.jobs > 0 else (os.cpu_count() or 1)
    worker_count = max(1, min(worker_count, len(funcs)))

    if worker_count == 1:
        for func in funcs:
            results.append(compile_function(func))
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(compile_function, func) for func in funcs]
            for future in as_completed(futures):
                results.append(future.result())

    report_md = runtime_root / "bytespace-report-runtime.md"
    report_csv = runtime_root / "bytespace-report-runtime.csv"

    rows = []
    for name, size, savings in results:
        if size is None:
            continue
        savings_pct = (savings / base_size) * 100
        rows.append((name, size, savings, savings_pct))

    rows.sort(key=lambda r: r[2], reverse=True)

    md_lines = [
        "# Runtime bytespace report",
        "",
        f"- Base size: {base_size} bytes",
        "",
        "| Function | New size (bytes) | Savings (bytes) | Savings (%) |",
        "| --- | --- | --- | --- |",
    ]
    for name, size, savings, pct in rows:
        md_lines.append(f"| {name} | {size} | {savings} | {pct:.2f} |")
    report_md.write_text("\n".join(md_lines) + "\n")

    with report_csv.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["function", "base_size", "new_size", "savings", "savings_pct"])
        for name, size, savings, pct in rows:
            writer.writerow([name, base_size, size, savings, f"{pct:.2f}"])

    print(f"Base runtime size: {base_size}")
    print(report_md)
    print(report_csv)


if __name__ == "__main__":
    main()
