"""Unit tests for search refinement and synthesis report generation."""

import json
from pathlib import Path
import pytest
import respx

from research_engine.config import LLMConfig
from research_engine.database import DatabaseManager
from research_engine.export.report import ResearchReportGenerator
from research_engine.llm.client import LLMClient
from research_engine.models import (
    ConceptMap,
    PlanStatus,
    ReviewMode,
    SearchPlan,
    SearchQueryPlan,
)
from research_engine.planner.generator import ResearchPlanner
from research_engine.planner.refiner import SearchRefiner


@respx.mock
def test_search_refinement_workflow(tmp_path: Path):
    db_file = tmp_path / "refine.db"
    db_mgr = DatabaseManager(db_file)
    db_mgr.initialize_schema()

    config = LLMConfig(base_url="http://mock-llm:5000/v1")
    llm = LLMClient(config)
    planner = ResearchPlanner(db_mgr, llm)

    # Base initial plan
    initial_plan = SearchPlan(
        plan_id="plan_test_iter",
        version=1,
        research_question="Does negative partisanship undermine public trust?",
        concept_map=ConceptMap(
            core_concepts=["negative partisanship", "public trust"],
            synonyms={"negative partisanship": ["out-party hostility"]},
            related_concepts=["affective polarization"],
            competing_explanations=["economic hardship"],
        ),
        queries=[
            SearchQueryPlan(
                query_id="q1",
                target_database="openalex",
                query_string="negative partisanship public trust",
                purpose="Initial query",
                is_approved=True,
            )
        ],
        status=PlanStatus.APPROVED,
    )
    planner.save_plan(initial_plan)

    # Record a search run referencing initial_plan so save_plan upsert is exercised under FK constraints
    from research_engine.provenance import ProvenanceTracker
    ProvenanceTracker(db_mgr).record_search_run(
        run_id="run_test_fk",
        plan_id=initial_plan.plan_id,
        plan_version=1,
        query_id="q1",
        target_database="openalex",
        query_string="negative partisanship public trust",
        total_results=10,
        records_retrieved=10,
        new_records=5,
    )

    mock_refinement_payload = {
        "coverage_gaps": ["Under-representation of comparative European parliamentary systems"],
        "missed_vocabulary": ["partisan incivility", "democratic disillusionment"],
        "stop_recommendation": False,
        "stop_reason": "Significant conceptual gaps remaining in European context.",
        "supplementary_queries": [
            {
                "target_database": "crossref",
                "query_string": '"partisan incivility" AND "democratic disillusionment"',
                "purpose": "Capture European comparative cases",
            }
        ],
    }

    respx.post("http://mock-llm:5000/v1/chat/completions").respond(
        status_code=200,
        json={"choices": [{"message": {"content": json.dumps(mock_refinement_payload)}}]},
    )

    refiner = SearchRefiner(db_mgr, llm)
    analysis, updated_plan = refiner.analyze_and_refine(initial_plan, budget_limit=5)

    assert analysis.stop_recommendation is False
    assert "partisan incivility" in analysis.missed_vocabulary[0]
    assert updated_plan.version == 2
    assert updated_plan.status == PlanStatus.DRAFT  # Needs approval
    assert len(updated_plan.queries) == 2
    # Ensure newly added query is unapproved
    assert updated_plan.queries[1].is_approved is False
    assert "supp" in updated_plan.queries[1].query_id

    # Approving the refined plan must also succeed without FK error
    approved_plan = planner.approve_plan(updated_plan.plan_id)
    assert approved_plan.status == PlanStatus.APPROVED

    # Verify report generation
    report_gen = ResearchReportGenerator(db_mgr)
    report_file = tmp_path / "report.md"
    md = report_gen.generate_report(updated_plan, output_path=report_file)

    assert "# Academic Research Synthesis:" in md
    assert "plan_test_iter" in md
    assert "PRISMA Flow" in md
    assert report_file.is_file()
