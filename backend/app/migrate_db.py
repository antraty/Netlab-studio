from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

from .education import EducationStore

_TABLES = (
    "users",
    "sessions",
    "auth_login_attempts",
    "account_invitations",
    "password_reset_tokens",
    "remote_workers",
    "worker_jobs",
    "execution_metrics",
    "alert_notifications",
    "cleanup_attempts",
    "execution_resources",
    "license_manifests",
    "license_acceptances",
    "execution_snapshots",
    "console_audit",
    "groups",
    "group_members",
    "assignments",
    "assignment_details",
    "student_labs",
    "student_lab_runtime",
    "student_submission_attempts",
    "laboratories",
    "laboratory_versions",
    "laboratory_members",
    "laboratory_events",
)


def migrate(source_path: Path, target_url: str) -> int:
    if not source_path.is_file():
        raise FileNotFoundError(f"source database not found: {source_path}")
    target = EducationStore(target_url)
    if not target.postgres:
        raise ValueError("migration target must be PostgreSQL")
    if target.user_count():
        raise ValueError("migration target must not contain accounts")

    source = sqlite3.connect(source_path)
    source.row_factory = sqlite3.Row
    try:
        available = {
            row["name"]
            for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        copied = 0
        with target._connect() as destination:
            for table in _TABLES:
                if table not in available:
                    continue
                rows = source.execute(f'SELECT * FROM "{table}"')
                columns = [column[0] for column in rows.description]
                column_list = ",".join(f'"{column}"' for column in columns)
                placeholders = ",".join("?" for _ in columns)
                statement = f'INSERT INTO "{table}" ({column_list}) VALUES ({placeholders})'
                for row in rows:
                    destination.execute(statement, tuple(row))
                    copied += 1
            destination.execute(
                "INSERT INTO laboratory_versions(laboratory_id,version,created_at,reason,topology_json) "
                "SELECT l.id,1,l.created_at,'migrated-current',l.topology_json FROM laboratories l "
                "WHERE NOT EXISTS (SELECT 1 FROM laboratory_versions v WHERE v.laboratory_id=l.id)"
            )
        return copied
    finally:
        source.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Copy Netlab account and laboratory records from SQLite to PostgreSQL.")
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(".netlab-data/education.sqlite3"),
        help="SQLite education database to copy",
    )
    arguments = parser.parse_args()
    target_url = os.getenv("NETLAB_DATABASE_URL", "")
    if not target_url:
        parser.error("set NETLAB_DATABASE_URL to the PostgreSQL target before running")
    copied = migrate(arguments.source, target_url)
    print(f"Copied {copied} records, including database-backed topology versions.")


if __name__ == "__main__":
    main()
