"""Unit tests for the AI Research Planner and LLM abstraction."""

import json
from pathlib import Path
import pytest
import respx
import httpx
from pydantic import BaseModel

from research_engine.config import LLMConfig
from research_engine.database import DatabaseManager
from research_engine.llm.client import LLMClient, LLMConnectionError
from research_engine.models import PlanStatus, ReviewMode
from research_engine.planner.generator import ResearchPlanner, RawPlannerOutput


class DummyModel(BaseModel):
    message: str


@respx.mock
def test_llm_client_generate_structured_success():
    config = LLMConfig(base_url="http://mock-llm:5000/v1", api_key="test-key", model="smart")
    client = LLMClient(config)

    mock_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({"message": "structured test output"})
                }
            }
        ]
    }

    respx.post("http://mock-llm:5000/v1/chat/completions").respond(
        status_code=200,
        json=mock_response,
    )

    result = client.generate_structured(
        system_prompt="Test system",
        user_prompt="Test user",
        response_model=DummyModel,
    )

    assert result.message == "structured test output"


@respx.mock
def test_llm_client_connection_error():
    config = LLMConfig(base_url="http://mock-llm:5000/v1", api_key="test-key", model="smart")
    client = LLMClient(config)

    respx.post("http://mock-llm:5000/v1/chat/completions").mock(
        side_effect=httpx.ConnectError("Network unreachable")
    )

    with pytest.raises(LLMConnectionError):
        client.generate_structured(
            system_prompt="Test system",
            user_prompt="Test user",
            response_model=DummyModel,
        )


@respx.mock
def test_planner_generate_plan_distinguishes_concepts(tmp_path: Path):
    db_file = tmp_path / "planner_test.db"
    db_mgr = DatabaseManager(db_file)
    db_mgr.initialize_schema()

    config = LLMConfig(base_url="http://mock-llm:5000/v1")
    llm = LLMClient(config)
    planner = ResearchPlanner(db_mgr, llm)

    mock_planner_payload = {
        "core_concepts": ["negative partisanship", "democratic backsliding"],
        "synonyms": {
            "negative partisanship": ["out-party hostility", "partisan animus"],
            "democratic backsliding": ["democratic erosion", "autocratization"],
        },
        "related_concepts": ["affective polarization", "ideological sorting"],
        "competing_explanations": ["economic inequality", "institutional decay"],
        "queries": [
            {
                "target_database": "openalex",
                "query_string": '"negative partisanship" AND "democratic backsliding"',
                "purpose": "Test direct intersection",
                "query_type": "focused",
            },
            {
                "target_database": "crossref",
                "query_string": '"affective polarization" AND "democratic erosion"',
                "purpose": "Capture adjacent terminology",
                "query_type": "supplementary",
            },
        ],
        "inclusion_criteria": [
            "Peer-reviewed political science and public administration literature",
            "Empirical or theoretical analysis of partisanship and democratic institutions",
        ],
        "exclusion_criteria": [
            "Non-scholarly op-eds and opinion essays",
            "Purely technical voting system simulations without political behavior",
        ],
    }

    respx.post("http://mock-llm:5000/v1/chat/completions").respond(
        status_code=200,
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(mock_planner_payload)
                    }
                }
            ]
        },
    )

    plan = planner.generate_plan(
        research_question="Does negative partisanship accelerate democratic backsliding?",
        theoretical_framework="Affective polarization and institutional erosion",
        discipline_scope="Political Science",
        review_mode=ReviewMode.EXPLORATORY,
    )

    # 1. Verify plan structure
    assert plan.status == PlanStatus.DRAFT
    assert plan.version == 1
    assert "negative partisanship" in plan.concept_map.core_concepts
    # Synonyms distinct from related concepts
    assert "out-party hostility" in plan.concept_map.synonyms["negative partisanship"]
    assert "affective polarization" in plan.concept_map.related_concepts
    assert "economic inequality" in plan.concept_map.competing_explanations
    assert len(plan.queries) == 2
    # Ensure unapproved initially
    assert all(not q.is_approved for q in plan.queries)

    # 2. Test persistence and retrieval
    retrieved = planner.get_plan(plan.plan_id)
    assert retrieved is not None
    assert retrieved.plan_id == plan.plan_id
    assert retrieved.research_question == plan.research_question
    assert len(retrieved.queries) == 2

    # 3. Test selective approval
    approved_plan = planner.approve_plan(plan.plan_id, query_ids=[plan.queries[0].query_id])
    assert approved_plan.status == PlanStatus.APPROVED
    assert approved_plan.approved_at is not None
    assert approved_plan.queries[0].is_approved is True
    assert approved_plan.queries[1].is_approved is False

    # 4. Verify markdown export
    md = planner.export_plan_markdown(approved_plan)
    assert "# Search Plan:" in md
    assert "negative partisanship" in md
    assert "affective polarization" in md
    assert "✓ YES" in md
