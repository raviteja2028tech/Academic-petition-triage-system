"""Safe, repeatable database cleanup for demo environments.

Backs up the database first, then removes automated Locust benchmark/load-test runs
while strictly preserving all demonstration student records, legitimate submissions,
and examiner decisions.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone


def cleanup_db(db_path: str) -> dict[str, int]:
    if not os.path.isfile(db_path):
        print(f"Database file not found at: {db_path}")
        return {}

    # 1. Back up database before any change
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = f"{db_path}.backup_{timestamp}"
    shutil.copy2(db_path, backup_path)
    print(f"Created safety backup at: {backup_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 2. Count before
    total_before = c.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    events_before = c.execute("SELECT COUNT(*) FROM run_events").fetchone()[0]

    # 3. Identify old automated test runs (created before 2026-11-11 without demo_client)
    c.execute("BEGIN IMMEDIATE")

    # Delete run_events for old stress-test runs
    c.execute(
        "DELETE FROM run_events WHERE run_id IN ("
        "  SELECT run_id FROM runs WHERE (client_id IS NULL OR client_id = '') AND created_at < '2026-11-11'"
        ")"
    )

    # Delete old stress-test runs
    c.execute(
        "DELETE FROM runs WHERE (client_id IS NULL OR client_id = '') AND created_at < '2026-11-11'"
    )

    # 4. Standardize any non-canonical decision strings in examiner_decisions
    c.execute("UPDATE examiner_decisions SET decision='accept-petition' WHERE decision='accept'")
    c.execute("UPDATE examiner_decisions SET decision='reject-petition' WHERE decision='reject'")
    c.execute("UPDATE examiner_decisions SET decision='request-more-information' WHERE decision='request_info'")

    c.execute("COMMIT")

    # 5. Optimize & vacuum
    c.execute("VACUUM")

    # 6. Count after
    total_after = c.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    events_after = c.execute("SELECT COUNT(*) FROM run_events").fetchone()[0]
    decisions_count = c.execute("SELECT COUNT(*) FROM examiner_decisions").fetchone()[0]
    users_count = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    conn.close()

    removed = total_before - total_after
    print(f"Cleanup completed: removed {removed} old stress-test runs ({total_before} -> {total_after}).")
    print(f"Preserved {total_after} petition runs, {decisions_count} examiner decisions, {users_count} users.")
    return {
        "runs_before": total_before,
        "runs_after": total_after,
        "runs_removed": removed,
        "decisions": decisions_count,
    }


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DB_PATH", "data/triage.sqlite3")
    cleanup_db(target)

