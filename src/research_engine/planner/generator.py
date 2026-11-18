"""AI Research Planner: Analyzes research questions and produces reviewable, versioned plans."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Any

from research_engine.database import DatabaseManager
from research_engine.llm.client import LLMClient
from research_engine.llm.prompts import PLANNER_SYSTEM_PROMPT
from research_engine.models import (
    ConceptMap,
    PlanStatus,
    ReviewMode,
    SearchPlan,
    SearchQueryPlan,
)


class RawPlannerOutput(BaseModel):
    """Raw structured output expected from LLM."""
    core_concepts: list[str] = Field(description="Primary concepts directly derived from the question")
    synonyms: dict[str, list[str]] = Field(description="Synonyms and spelling variants mapped per core concept")
    related_concepts: list[str] = Field(description="Related but theoretically non-equivalent concepts")
    competing_explanations: list[str] = Field(description="Alternative or rival theoretical perspectives")
    queries: list[dict[str, Any]] = Field(
        description="List of proposed queries with target_database, query_string, purpose, query_type"
    )
    inclusion_criteria: list[str] = Field(description="Eligibility criteria for screening papers")
    exclusion_criteria: list[str] = Field(description="Exclusion criteria for screening papers")


class ResearchPlanner:
    """Orchestrates search plan generation, persistence, approval, and versioning."""

    def __init__(self, db_manager: DatabaseManager, llm_client: LLMClient):
        self.db = db_manager
        self.llm = llm_client

    def generate_plan(
        self,
        research_question: str,
        theoretical_framework: str | None = None,
        discipline_scope: str | None = "Political Science and Public Administration",
        review_mode: ReviewMode = ReviewMode.EXPLORATORY,
        target_databases: list[str] | None = None,
    ) -> SearchPlan:
        """Call LLM to construct a structured SearchPlan and save it as a draft in SQLite."""
        targets = target_databases or ["openalex", "crossref", "semanticscholar"]

        user_prompt = f"""RESEARCH QUESTION: {research_question}
THEORETICAL FRAMEWORK: {theoretical_framework or 'Not explicitly specified'}
DISCIPLINE SCOPE: {discipline_scope or 'Interdisciplinary'}
REVIEW MODE: {review_mode.value}
TARGET DATABASES: {', '.join(targets)}

Please develop a comprehensive search plan following the instructions."""

        raw_output = self.llm.generate_structured(
            system_prompt=PLANNER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=RawPlannerOutput,
        )

        plan_id = f"plan_{uuid.uuid4().hex[:10]}"
        now = datetime.now(timezone.utc)

        concept_map = ConceptMap(
            core_concepts=raw_output.core_concepts,
            synonyms=raw_output.synonyms,
            related_concepts=raw_output.related_concepts,
            competing_explanations=raw_output.competing_explanations,
        )

        query_plans: list[SearchQueryPlan] = []
        for idx, q_dict in enumerate(raw_output.queries, start=1):
            q_id = f"{plan_id}_q{idx}"
            query_plans.append(
                SearchQueryPlan(
                    query_id=q_id,
                    target_database=q_dict.get("target_database", "openalex"),
                    query_string=q_dict.get("query_string", ""),
                    purpose=q_dict.get("purpose", ""),
                    query_type=q_dict.get("query_type", "broad"),
                    filters=q_dict.get("filters", {}),
                    is_approved=False,
                )
            )

        plan = SearchPlan(
            plan_id=plan_id,
            version=1,
            research_question=research_question,
            theoretical_framework=theoretical_framework,
            discipline_scope=discipline_scope,
            review_mode=review_mode,
            concept_map=concept_map,
            queries=query_plans,
            inclusion_criteria=raw_output.inclusion_criteria,
            exclusion_criteria=raw_output.exclusion_criteria,
            status=PlanStatus.DRAFT,
            created_at=now,
            approved_at=None,
        )

        self.save_plan(plan)
        return plan

    def save_plan(self, plan: SearchPlan) -> None:
        """Persist or update a search plan and its queries in SQLite."""
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO search_plans (
                    plan_id, version, research_question, theoretical_framework,
                    discipline_scope, review_mode, concept_map_json,
                    inclusion_criteria_json, exclusion_criteria_json, status,
                    created_at, approved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(plan_id) DO UPDATE SET
                    version = excluded.version,
                    research_question = excluded.research_question,
                    theoretical_framework = excluded.theoretical_framework,
                    discipline_scope = excluded.discipline_scope,
                    review_mode = excluded.review_mode,
                    concept_map_json = excluded.concept_map_json,
                    inclusion_criteria_json = excluded.inclusion_criteria_json,
                    exclusion_criteria_json = excluded.exclusion_criteria_json,
                    status = excluded.status,
                    approved_at = excluded.approved_at
                """,
                (
                    plan.plan_id,
                    plan.version,
                    plan.research_question,
                    plan.theoretical_framework,
                    plan.discipline_scope,
                    plan.review_mode.value,
                    json.dumps(plan.concept_map.model_dump(), ensure_ascii=False),
                    json.dumps(plan.inclusion_criteria, ensure_ascii=False),
                    json.dumps(plan.exclusion_criteria, ensure_ascii=False),
                    plan.status.value,
                    plan.created_at.isoformat(),
                    plan.approved_at.isoformat() if plan.approved_at else None,
                ),
            )

            # Insert queries
            for q in plan.queries:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO search_queries (
                        query_id, plan_id, target_database, query_string,
                        purpose, query_type, filters_json, is_approved
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        q.query_id,
                        plan.plan_id,
                        q.target_database,
                        q.query_string,
                        q.purpose,
                        q.query_type,
                        json.dumps(q.filters, ensure_ascii=False),
                        1 if q.is_approved else 0,
                    ),
                )

    def get_plan(self, plan_id: str) -> SearchPlan | None:
        """Load a search plan by its plan_id."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT plan_id, version, research_question, theoretical_framework,
                       discipline_scope, review_mode, concept_map_json,
                       inclusion_criteria_json, exclusion_criteria_json, status,
                       created_at, approved_at
                FROM search_plans
                WHERE plan_id = ?
                """,
                (plan_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            # Fetch queries
            cursor.execute(
                """
                SELECT query_id, target_database, query_string, purpose,
                       query_type, filters_json, is_approved
                FROM search_queries
                WHERE plan_id = ?
                ORDER BY query_id ASC
                """,
                (plan_id,),
            )
            query_rows = cursor.fetchall()

        concept_map_dict = json.loads(row["concept_map_json"]) if row["concept_map_json"] else {}
        inclusion_criteria = json.loads(row["inclusion_criteria_json"]) if row["inclusion_criteria_json"] else []
        exclusion_criteria = json.loads(row["exclusion_criteria_json"]) if row["exclusion_criteria_json"] else []

        queries = [
            SearchQueryPlan(
                query_id=q["query_id"],
                target_database=q["target_database"],
                query_string=q["query_string"],
                purpose=q["purpose"],
                query_type=q["query_type"],
                filters=json.loads(q["filters_json"]) if q["filters_json"] else {},
                is_approved=bool(q["is_approved"]),
            )
            for q in query_rows
        ]

        created_at = datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(timezone.utc)
        approved_at = datetime.fromisoformat(row["approved_at"]) if row["approved_at"] else None

        return SearchPlan(
            plan_id=row["plan_id"],
            version=row["version"],
            research_question=row["research_question"],
            theoretical_framework=row["theoretical_framework"],
            discipline_scope=row["discipline_scope"],
            review_mode=ReviewMode(row["review_mode"]),
            concept_map=ConceptMap(**concept_map_dict),
            queries=queries,
            inclusion_criteria=inclusion_criteria,
            exclusion_criteria=exclusion_criteria,
            status=PlanStatus(row["status"]),
            created_at=created_at,
            approved_at=approved_at,
        )

    def get_latest_plan(self) -> SearchPlan | None:
        """Fetch the most recently created search plan."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT plan_id FROM search_plans ORDER BY created_at DESC LIMIT 1")
            row = cursor.fetchone()
            if not row:
                return None
            return self.get_plan(row["plan_id"])

    def approve_plan(self, plan_id: str, query_ids: list[str] | None = None) -> SearchPlan:
        """Approve a plan and optionally filter which queries are approved."""
        plan = self.get_plan(plan_id)
        if not plan:
            raise ValueError(f"Search plan '{plan_id}' not found.")

        now = datetime.now(timezone.utc)
        plan.status = PlanStatus.APPROVED
        plan.approved_at = now

        for q in plan.queries:
            if query_ids is None or q.query_id in query_ids:
                q.is_approved = True
            else:
                q.is_approved = False

        self.save_plan(plan)
        return plan

    def export_plan_markdown(self, plan: SearchPlan, output_path: Path | str | None = None) -> str:
        """Generate human-readable markdown artifact of the search strategy."""
        lines = [
            f"# Search Plan: {plan.plan_id} (v{plan.version})",
            "",
            f"- **Research Question:** {plan.research_question}",
            f"- **Theoretical Framework:** {plan.theoretical_framework or 'Not specified'}",
            f"- **Discipline Scope:** {plan.discipline_scope or 'Multidisciplinary'}",
            f"- **Review Mode:** {plan.review_mode.value.capitalize()}",
            f"- **Status:** {plan.status.value.upper()}",
            f"- **Created At:** {plan.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"- **Approved At:** {plan.approved_at.strftime('%Y-%m-%d %H:%M:%S UTC') if plan.approved_at else 'Pending approval'}",
            "",
            "## 1. Concept Map",
            "",
            "### Core Concepts & Synonyms",
        ]

        for core in plan.concept_map.core_concepts:
            syns = plan.concept_map.synonyms.get(core, [])
            syn_str = ", ".join(f"`{s}`" for s in syns) if syns else "*None specified*"
            lines.append(f"- **{core}**: {syn_str}")

        lines.extend([
            "",
            "### Related Concepts (Non-Equivalent)",
        ])
        for rel in plan.concept_map.related_concepts:
            lines.append(f"- {rel}")

        lines.extend([
            "",
            "### Competing Theoretical Explanations",
        ])
        for comp in plan.concept_map.competing_explanations:
            lines.append(f"- {comp}")

        lines.extend([
            "",
            "## 2. Proposed Queries",
            "",
            "| ID | Target Database | Type | Approved | Purpose | Query String |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ])

        for q in plan.queries:
            app_str = "✓ YES" if q.is_approved else "✗ NO"
            clean_q = q.query_string.replace("|", "\\|")
            lines.append(
                f"| `{q.query_id}` | `{q.target_database}` | {q.query_type} | {app_str} | {q.purpose} | `{clean_q}` |"
            )

        lines.extend([
            "",
            "## 3. Screening Criteria",
            "",
            "### Inclusion Criteria",
        ])
        for inc in plan.inclusion_criteria:
            lines.append(f"- {inc}")

        lines.extend([
            "",
            "### Exclusion Criteria",
        ])
        for exc in plan.exclusion_criteria:
            lines.append(f"- {exc}")

        content = "\n".join(lines) + "\n"

        if output_path:
            p = Path(output_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")

        return content
