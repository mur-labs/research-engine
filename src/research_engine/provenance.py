"""Provenance tracking and execution logging."""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from research_engine.database import DatabaseManager


class ProvenanceTracker:
    """Records search runs, query executions, and PRISMA accounting."""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def record_search_run(
        self,
        run_id: str,
        plan_id: str,
        plan_version: int,
        query_id: str | None,
        target_database: str,
        query_string: str,
        total_results: int,
        records_retrieved: int,
        new_records: int,
        error_message: str | None = None,
    ) -> None:
        """Record an executed search run in SQLite."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO search_runs (
                    run_id, plan_id, plan_version, query_id, target_database,
                    query_string, total_results_found, records_retrieved,
                    new_records_added, error_message, executed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    plan_id,
                    plan_version,
                    query_id,
                    target_database,
                    query_string,
                    total_results,
                    records_retrieved,
                    new_records,
                    error_message,
                    now_iso,
                ),
            )

    def record_search_result(
        self,
        result_id: str,
        run_id: str,
        work_id: str,
        raw_payload: dict[str, Any],
    ) -> None:
        """Link a specific search run to a retrieved work, storing raw metadata."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO search_results (
                    result_id, run_id, work_id, raw_payload_json, retrieved_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    result_id,
                    run_id,
                    work_id,
                    json.dumps(raw_payload, ensure_ascii=False),
                    now_iso,
                ),
            )

    def get_run_summary(self, plan_id: str | None = None) -> list[dict[str, Any]]:
        """Retrieve execution history for auditing and PRISMA reporting."""
        query = """
            SELECT run_id, plan_id, plan_version, target_database, query_string,
                   total_results_found, records_retrieved, new_records_added,
                   error_message, executed_at
            FROM search_runs
        """
        params: list[Any] = []
        if plan_id:
            query += " WHERE plan_id = ?"
            params.append(plan_id)
        query += " ORDER BY executed_at DESC"

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
