"""Unit tests for provenance tracking."""

from pathlib import Path
from research_engine.database import DatabaseManager
from research_engine.provenance import ProvenanceTracker


def test_record_search_run_and_summary(tmp_path: Path):
    db_file = tmp_path / "prov.db"
    mgr = DatabaseManager(db_file)
    mgr.initialize_schema()

    tracker = ProvenanceTracker(mgr)

    # First insert a valid search plan
    with mgr.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO search_plans (
                plan_id, version, research_question, review_mode, status
            ) VALUES ('p1', 1, 'Does affective polarization reduce democratic backsliding?', 'exploratory', 'approved')
            """
        )

    # Record search run
    tracker.record_search_run(
        run_id="run-001",
        plan_id="p1",
        plan_version=1,
        query_id=None,
        target_database="openalex",
        query_string="affective polarization democratic backsliding",
        total_results=42,
        records_retrieved=25,
        new_records=25,
        error_message=None,
    )

    summary = tracker.get_run_summary(plan_id="p1")
    assert len(summary) == 1
    assert summary[0]["run_id"] == "run-001"
    assert summary[0]["total_results_found"] == 42
    assert summary[0]["records_retrieved"] == 25
    assert summary[0]["new_records_added"] == 25
