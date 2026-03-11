#!/usr/bin/env python3
import argparse
import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ReportData:
    status: str
    base_size: int | None
    funcs: dict[str, int]
    error: str | None


def parse_report_metadata(md_path: Path) -> tuple[str, int | None, str | None]:
    if not md_path.exists():
        return ("missing", None, None)

    status = "success"
    base_size = None
    error = None
    for line in md_path.read_text().splitlines():
        if line.startswith("- Base size:"):
            parts = line.split(":", 1)[1].strip().split()
            if parts:
                base_size = int(parts[0])
        elif line.startswith("- Status:"):
            status = line.split(":", 1)[1].strip()
        elif line.startswith("- Error:"):
            error = line.split(":", 1)[1].strip()

    return status, base_size, error


def load_report(csv_path: Path) -> ReportData:
    sizes: dict[str, int] = {}
    md_path = csv_path.with_suffix(".md")
    status, base_size, error = parse_report_metadata(md_path)

    if csv_path.exists():
        with csv_path.open() as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if base_size is None and row.get("base_size"):
                    base_size = int(row["base_size"])
                if row.get("function") and row.get("savings"):
                    sizes[row["function"]] = int(row["savings"])

    if csv_path.exists() and status == "missing":
        status = "success"

    return ReportData(status=status, base_size=base_size, funcs=sizes, error=error)


def format_delta(value: int) -> str:
    return f"{value:+d}"


def summarize_error(error: str | None) -> str:
    if not error:
        return "Unknown compile error"
    lines = [line.strip() for line in error.splitlines() if line.strip()]
    return lines[0] if lines else "Unknown compile error"


def build_report(
    contract: str,
    base_report: ReportData,
    head_report: ReportData,
    deltas: list[tuple[str, int, int, int]],
) -> str:
    if base_report.status == "failed":
        lines = [
            f"### {contract}",
            "",
            "- Base compilation failed; skipping runtime bytespace comparison.",
        ]
        if head_report.base_size is not None:
            lines.append(f"- Head runtime size: {head_report.base_size} bytes")
        lines.append(f"- Base error: `{summarize_error(base_report.error)}`")
        return "\n".join(lines)

    base_size = base_report.base_size or 0
    head_size = head_report.base_size or 0
    total_delta = head_size - base_size
    if not deltas and total_delta == 0:
        return ""

    lines = [
        f"### {contract}",
        "",
        f"- Base runtime size: {base_size} bytes",
        f"- Head runtime size: {head_size} bytes",
        f"- Delta: {format_delta(total_delta)} bytes",
    ]

    if deltas:
        lines.extend(
            [
                "",
                "| Function | Base (bytes) | Head (bytes) | Delta (bytes) |",
                "| --- | --- | --- | --- |",
            ]
        )
        for name, base, head, delta in deltas:
            lines.append(f"| {name} | {base} | {head} | {format_delta(delta)} |")
    else:
        lines.extend(["", "_No function-level size changes detected._"])

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare runtime bytespace reports for a contract."
    )
    parser.add_argument("--base", required=True, help="Base report CSV path.")
    parser.add_argument("--head", required=True, help="Head report CSV path.")
    parser.add_argument("--contract", required=True, help="Contract label.")
    parser.add_argument("--output", help="Write report to file instead of stdout.")
    args = parser.parse_args()

    base_report = load_report(Path(args.base))
    head_report = load_report(Path(args.head))

    all_funcs = sorted(set(base_report.funcs) | set(head_report.funcs))
    deltas: list[tuple[str, int, int, int]] = []
    for name in all_funcs:
        base = base_report.funcs.get(name, 0)
        head = head_report.funcs.get(name, 0)
        delta = head - base
        if delta != 0:
            deltas.append((name, base, head, delta))

    deltas.sort(key=lambda row: abs(row[3]), reverse=True)
    report = build_report(args.contract, base_report, head_report, deltas)

    if args.output:
        Path(args.output).write_text(report)
    else:
        print(report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
