#!/usr/bin/env python3
import argparse
import json
import sqlite3
import time
from pathlib import Path


def get_latest_run_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT run_id FROM _smithers_runs ORDER BY created_at_ms DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def get_total_targets(conn: sqlite3.Connection, run_id: str) -> int:
    row = conn.execute(
        """
        SELECT json_array_length(targets)
        FROM discovery
        WHERE run_id = ? AND node_id = 'discover-targets'
        ORDER BY iteration DESC
        LIMIT 1
        """,
        (run_id,),
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def get_started_functions(conn: sqlite3.Connection, run_id: str) -> int:
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT json_extract(payload_json, '$.nodeId'))
        FROM _smithers_events
        WHERE run_id = ?
          AND type = 'NodeStarted'
          AND json_extract(payload_json, '$.nodeId') LIKE '%:write'
        """,
        (run_id,),
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def get_approved_functions(conn: sqlite3.Connection, run_id: str) -> int:
    row = conn.execute(
        """
        WITH latest_review AS (
          SELECT r.node_id, r.approved
          FROM review r
          JOIN (
            SELECT node_id, MAX(iteration) AS max_iteration
            FROM review
            WHERE run_id = ?
            GROUP BY node_id
          ) x
            ON r.node_id = x.node_id
           AND r.iteration = x.max_iteration
          WHERE r.run_id = ?
        )
        SELECT COUNT(*)
        FROM latest_review
        WHERE approved = 1
        """,
        (run_id, run_id),
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def get_current_writer(conn: sqlite3.Connection, run_id: str) -> str | None:
    row = conn.execute(
        """
        SELECT json_extract(payload_json, '$.nodeId')
        FROM _smithers_events
        WHERE run_id = ?
          AND type = 'NodeStarted'
          AND json_extract(payload_json, '$.nodeId') LIKE '%:write'
        ORDER BY seq DESC
        LIMIT 1
        """,
        (run_id,),
    ).fetchone()
    return row[0] if row else None


def short_name(node_id: str | None) -> str:
    if not node_id:
        return "(none)"
    left = node_id.split(":", 1)[0]
    parts = left.split("-")
    if len(parts) >= 3:
        contract = parts[2].capitalize()
        fn = "_".join(parts[4:]) if len(parts) > 4 else parts[-1]
        return f"{contract}.{fn}"
    return node_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor Smithers matrix progress")
    parser.add_argument("--db", default=".tmp/unitary-matrix-loop.db")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--interval", type=float, default=3.0)
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"DB not found: {db_path}")
        return

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    run_id = args.run_id or get_latest_run_id(conn)
    if not run_id:
        print("No run found")
        return

    print(f"Monitoring run {run_id}\n")

    last_started = -1
    last_approved = -1
    last_current = None

    while True:
        total = get_total_targets(conn, run_id)
        started = get_started_functions(conn, run_id)
        approved = get_approved_functions(conn, run_id)
        current = get_current_writer(conn, run_id)

        if (started, approved, current) != (last_started, last_approved, last_current):
            started_pct = (started / total * 100.0) if total else 0.0
            approved_pct = (approved / total * 100.0) if total else 0.0
            print(
                f"Started: {started}/{total} ({started_pct:.1f}%) | "
                f"Approved: {approved}/{total} ({approved_pct:.1f}%)"
            )
            print(f"Current: {short_name(current)}\n")
            last_started, last_approved, last_current = started, approved, current

        status_row = conn.execute(
            "SELECT status FROM _smithers_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        status = status_row[0] if status_row else "unknown"
        if status in {"finished", "failed", "cancelled"}:
            print(f"Run status: {status}")
            break

        time.sleep(args.interval)


if __name__ == "__main__":
    main()
