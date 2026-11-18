"""Unit tests for SQLite database manager and schema initialization."""

from pathlib import Path
import sqlite3
import pytest
from research_engine.database import DatabaseManager, SCHEMA_VERSION


def test_database_initialization(tmp_path: Path):
    db_file = tmp_path / "test.db"
    mgr = DatabaseManager(db_file)
    assert mgr.get_applied_version() == 0

    mgr.initialize_schema()
    assert mgr.get_applied_version() == SCHEMA_VERSION

    # Verify tables created
    with mgr.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cursor.fetchall()}

    expected_tables = {
        "schema_migrations",
        "search_plans",
        "search_queries",
        "search_runs",
        "works",
        "authors",
        "authorships",
        "work_identifiers",
        "search_results",
        "retrievals",
        "evidence_records",
    }
    assert expected_tables.issubset(tables)


def test_database_foreign_keys_and_transactions(tmp_path: Path):
    db_file = tmp_path / "fk_test.db"
    mgr = DatabaseManager(db_file)
    mgr.initialize_schema()

    # Foreign key violation should raise IntegrityError and rollback
    with pytest.raises(sqlite3.IntegrityError):
        with mgr.get_connection() as conn:
            # Insert search query referencing nonexistent plan_id
            conn.execute(
                """
                INSERT INTO search_queries (
                    query_id, plan_id, target_database, query_string,
                    purpose, query_type, is_approved
                ) VALUES ('q1', 'nonexistent_plan', 'openalex', 'test', 'purpose', 'broad', 0)
                """
            )
