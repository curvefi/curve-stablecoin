#!/usr/bin/env python3
import argparse
import csv
from pathlib import Path


def parse_base_size(md_path: Path) -> int | None:
    if not md_path.exists():
        return None
    for line in md_path.read_text().splitlines():
        if line.startswith("- Base size:"):
            parts = line.split(":", 1)[1].strip().split()
            if parts:
                return int(parts[0])
    return None


def load_report(csv_path: Path) -> tuple[int, dict[str, int]]:
    sizes: dict[str, int] = {}
    base_size: int | None = None
    if csv_path.exists():
        with csv_path.open() as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if base_size is None and row.get("base_size"):
                    base_size = int(row["base_size"])
                if row.get("function") and row.get("savings"):
                    sizes[row["function"]] = int(row["savings"])

    if base_size is None:
        base_size = parse_base_size(csv_path.with_suffix(".md"))

    return base_size or 0, sizes


def format_delta(value: int) -> str:
    return f"{value:+d}"


def build_report(
    contract: str,
    base_size: int,
    head_size: int,
    deltas: list[tuple[str, int, int, int]],
) -> str:
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

    base_size, base_funcs = load_report(Path(args.base))
    head_size, head_funcs = load_report(Path(args.head))

    all_funcs = sorted(set(base_funcs) | set(head_funcs))
    deltas: list[tuple[str, int, int, int]] = []
    for name in all_funcs:
        base = base_funcs.get(name, 0)
        head = head_funcs.get(name, 0)
        delta = head - base
        if delta != 0:
            deltas.append((name, base, head, delta))

    deltas.sort(key=lambda row: abs(row[3]), reverse=True)
    report = build_report(args.contract, base_size, head_size, deltas)

    if args.output:
        Path(args.output).write_text(report)
    else:
        print(report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
