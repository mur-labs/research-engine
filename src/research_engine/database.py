"""SQLite database connection and schema migrations."""

import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import Generator

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS search_plans (
    plan_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    research_question TEXT NOT NULL,
    theoretical_framework TEXT,
    discipline_scope TEXT,
    review_mode TEXT NOT NULL,
    concept_map_json TEXT,
    inclusion_criteria_json TEXT,
    exclusion_criteria_json TEXT,
    status TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    approved_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS search_queries (
    query_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    target_database TEXT NOT NULL,
    query_string TEXT NOT NULL,
    purpose TEXT NOT NULL,
    query_type TEXT NOT NULL,
    filters_json TEXT,
    is_approved BOOLEAN NOT NULL DEFAULT 0,
    FOREIGN KEY (plan_id) REFERENCES search_plans (plan_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS search_runs (
    run_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    plan_version INTEGER NOT NULL,
    query_id TEXT,
    target_database TEXT NOT NULL,
    query_string TEXT NOT NULL,
    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total_results_found INTEGER DEFAULT 0,
    records_retrieved INTEGER DEFAULT 0,
    new_records_added INTEGER DEFAULT 0,
    error_message TEXT,
    FOREIGN KEY (plan_id) REFERENCES search_plans (plan_id)
);

CREATE TABLE IF NOT EXISTS works (
    work_id TEXT PRIMARY KEY,
    doi TEXT UNIQUE,
    title TEXT NOT NULL,
    publication_year INTEGER,
    publication_date TEXT,
    venue TEXT,
    publisher TEXT,
    volume TEXT,
    issue TEXT,
    pages TEXT,
    abstract TEXT,
    citation_count INTEGER,
    is_oa BOOLEAN DEFAULT 0,
    oa_url TEXT,
    landing_page_url TEXT,
    zotero_key TEXT,
    screening_decision TEXT DEFAULT 'unscreened',
    retrieval_status TEXT DEFAULT 'metadata_only',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_works_doi ON works(doi);
CREATE INDEX IF NOT EXISTS idx_works_title ON works(title);
CREATE INDEX IF NOT EXISTS idx_works_screening ON works(screening_decision);
CREATE INDEX IF NOT EXISTS idx_works_retrieval ON works(retrieval_status);

CREATE TABLE IF NOT EXISTS authors (
    author_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    orcid TEXT,
    affiliation TEXT
);

CREATE TABLE IF NOT EXISTS authorships (
    work_id TEXT NOT NULL,
    author_id TEXT NOT NULL,
    author_position INTEGER,
    PRIMARY KEY (work_id, author_id),
    FOREIGN KEY (work_id) REFERENCES works (work_id) ON DELETE CASCADE,
    FOREIGN KEY (author_id) REFERENCES authors (author_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS work_identifiers (
    work_id TEXT NOT NULL,
    identifier_type TEXT NOT NULL,
    identifier_value TEXT NOT NULL,
    PRIMARY KEY (identifier_type, identifier_value),
    FOREIGN KEY (work_id) REFERENCES works (work_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS search_results (
    result_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    work_id TEXT NOT NULL,
    raw_payload_json TEXT,
    retrieved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES search_runs (run_id),
    FOREIGN KEY (work_id) REFERENCES works (work_id)
);

CREATE TABLE IF NOT EXISTS retrievals (
    retrieval_id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL,
    status TEXT NOT NULL,
    source_url TEXT,
    file_path TEXT,
    file_hash TEXT,
    file_size_bytes INTEGER,
    error_message TEXT,
    attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (work_id) REFERENCES works (work_id)
);

CREATE TABLE IF NOT EXISTS evidence_records (
    evidence_id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    content TEXT NOT NULL,
    page_start INTEGER,
    page_end INTEGER,
    supporting_passage TEXT,
    confidence_score REAL,
    is_verified BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (work_id) REFERENCES works (work_id)
);
"""


class DatabaseManager:
    """Manages SQLite database connections, schema creation, and transactions."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Provide a transactional database connection."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize_schema(self) -> None:
        """Apply base schema and track migrations."""
        with self.get_connection() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )

    def get_applied_version(self) -> int:
        """Return the current applied schema version or 0 if not initialized."""
        if not self.db_path.exists():
            return 0
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                )
                row = cursor.fetchone()
                return int(row[0]) if row and row[0] is not None else 0
        except sqlite3.OperationalError:
            return 0
