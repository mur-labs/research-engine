"""Unit tests for the DeduplicationEngine and SearchExecutor."""

from pathlib import Path
import pytest
import respx

from research_engine.config import AppConfig
from research_engine.database import DatabaseManager
from research_engine.deduplication.engine import (
    DeduplicationEngine,
    normalize_title,
    normalize_author_family,
)
from research_engine.models import Author, Work, PlanStatus, ReviewMode, SearchPlan, SearchQueryPlan
from research_engine.planner.generator import ResearchPlanner
from research_engine.search.executor import SearchExecutor
from research_engine.export.exporters import export_works_to_bibtex, export_works_to_csv


def test_normalize_title_and_author():
    assert normalize_title("Affective Polarization & Democratic Erosion: A Test!") == "affective polarization and democratic erosion a test"
    assert normalize_title("Café & Résumé (Analysis)") == "cafe and resume analysis"
    assert normalize_author_family("Jane Doe") == "doe"
    assert normalize_author_family("Juan Carlos Gomez-Hernandez") == "gomezhernandez"


def test_deduplication_doi_precedence(tmp_path: Path):
    db_file = tmp_path / "dedup_doi.db"
    db_mgr = DatabaseManager(db_file)
    db_mgr.initialize_schema()

    dedup = DeduplicationEngine(db_mgr)

    work1 = Work(
        work_id="w1",
        doi="10.1017/s0003055420000123",
        title="Partisan Animus in Modern Elections",
        authors=[Author(name="Jane Doe")],
        publication_year=2021,
    )
    saved1, is_new1 = dedup.merge_or_insert_work(work1)
    assert is_new1 is True

    # Candidate with same DOI but slightly different title formatting and more metadata
    work2 = Work(
        work_id="w2",
        doi="10.1017/S0003055420000123",  # Different casing
        title="Partisan animus in modern elections.",
        authors=[Author(name="Jane Doe")],
        publication_year=2021,
        abstract="Enriched abstract from second database.",
        citation_count=50,
    )
    saved2, is_new2 = dedup.merge_or_insert_work(work2)
    assert is_new2 is False
    assert saved2.work_id == "w1"  # Preserved original ID
    assert saved2.abstract == "Enriched abstract from second database."
    assert saved2.citation_count == 50


def test_deduplication_fuzzy_title_and_author(tmp_path: Path):
    db_file = tmp_path / "dedup_fuzzy.db"
    db_mgr = DatabaseManager(db_file)
    db_mgr.initialize_schema()

    dedup = DeduplicationEngine(db_mgr)

    work1 = Work(
        work_id="w1",
        doi=None,  # No DOI
        title="Negative Partisanship and Affective Polarization in America",
        authors=[Author(name="Robert Mason")],
        publication_year=2020,
    )
    saved1, is_new1 = dedup.merge_or_insert_work(work1)
    assert is_new1 is True

    # Matching title + author + year without DOI
    candidate = Work(
        work_id="w2",
        doi=None,
        title="Negative partisanship & affective polarization in America!",
        authors=[Author(name="R. Mason")],
        publication_year=2020,
        venue="Journal of Politics",
    )
    saved2, is_new2 = dedup.merge_or_insert_work(candidate)
    assert is_new2 is False
    assert saved2.work_id == "w1"
    assert saved2.venue == "Journal of Politics"


@respx.mock
def test_search_executor_enforces_approved_queries_only(tmp_path: Path):
    db_file = tmp_path / "executor.db"
    db_mgr = DatabaseManager(db_file)
    db_mgr.initialize_schema()

    config = AppConfig()
    config.database.path = db_file
    executor = SearchExecutor(db_mgr, config)

    # Mock OpenAlex endpoint
    respx.get("https://api.openalex.org/works").respond(
        status_code=200,
        json={
            "meta": {"count": 1, "next_cursor": None},
            "results": [
                {
                    "id": "https://openalex.org/W999",
                    "doi": "https://doi.org/10.1086/711234",
                    "title": "Democratic Norms and Polarized Publics",
                    "publication_year": 2022,
                    "authorships": [{"author": {"display_name": "Sarah Connor"}}],
                }
            ],
        },
    )

    # 1. Plan with unapproved query should fail
    unapproved_query = SearchQueryPlan(
        query_id="q1",
        target_database="openalex",
        query_string="democratic norms polarization",
        purpose="Test unapproved gating",
        is_approved=False,
    )
    plan_draft = SearchPlan(
        plan_id="p_draft",
        research_question="Does polarization erode democratic norms?",
        queries=[unapproved_query],
        status=PlanStatus.DRAFT,
    )

    with pytest.raises(ValueError, match="No approved queries"):
        executor.execute_plan(plan_draft)

    # 2. Approve query and execute
    unapproved_query.is_approved = True
    plan_draft.status = PlanStatus.APPROVED
    
    # Save plan to db first so foreign key references in search_runs succeed
    planner = ResearchPlanner(db_mgr, None)
    planner.save_plan(plan_draft)

    runs = executor.execute_plan(plan_draft)

    assert len(runs) == 1
    assert runs[0].total_results_found == 1
    assert runs[0].records_retrieved == 1
    assert runs[0].new_records_added == 1
    assert runs[0].error_message is None

    # Check work saved in database
    retrieved = executor.dedup._load_work_by_id(runs[0].target_database)  # Check via query
    with db_mgr.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM works")
        count = cursor.fetchone()[0]
        assert count == 1


def test_export_bibtex_and_csv(tmp_path: Path):
    works = [
        Work(
            work_id="w1",
            doi="10.1017/s0003055420000123",
            title="Affective Polarization and Democratic Erosion",
            authors=[Author(name="Jane Doe")],
            publication_year=2021,
            venue="APSR",
        )
    ]

    bib_path = tmp_path / "export.bib"
    csv_path = tmp_path / "export.csv"

    export_works_to_bibtex(works, bib_path)
    export_works_to_csv(works, csv_path)

    bib_content = bib_path.read_text(encoding="utf-8")
    assert "@article{" in bib_content
    assert "doe2021_affective" in bib_content
    assert "Affective Polarization and Democratic Erosion" in bib_content

    csv_content = csv_path.read_text(encoding="utf-8")
    assert "10.1017/s0003055420000123" in csv_content
    assert "Jane Doe" in csv_content


def test_dedup_merge_upgrades_retrieval_status_on_oa_url(tmp_path: Path):
    from research_engine.models import RetrievalStatus

    db_mgr = DatabaseManager(tmp_path / "oa_upgrade.db")
    db_mgr.initialize_schema()
    dedup = DeduplicationEngine(db_mgr)

    w1 = Work(
        work_id="w1",
        doi="10.1000/oa.1",
        title="Open Access Upgrade Test",
        retrieval_status=RetrievalStatus.METADATA_ONLY,
    )
    dedup.merge_or_insert_work(w1)

    w2 = Work(
        work_id="w2",
        doi="10.1000/oa.1",
        title="Open Access Upgrade Test",
        is_oa=True,
        oa_url="https://example.org/paper.pdf",
        retrieval_status=RetrievalStatus.OA_LOCATION_FOUND,
    )
    merged, is_new = dedup.merge_or_insert_work(w2)
    assert is_new is False
    assert merged.retrieval_status == RetrievalStatus.OA_LOCATION_FOUND


def test_export_bibtex_deduplicates_citation_keys(tmp_path: Path):
    works = [
        Work(work_id="w1", title="The First Study", authors=[Author(name="Jane Doe")], publication_year=2021),
        Work(work_id="w2", title="The Second Study", authors=[Author(name="Jane Doe")], publication_year=2021),
    ]
    bib_path = tmp_path / "dups.bib"
    export_works_to_bibtex(works, bib_path)
    content = bib_path.read_text(encoding="utf-8")
    assert "@misc{doe2021_the," in content
    assert "@misc{doe2021_the_2," in content
