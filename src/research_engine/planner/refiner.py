"""Iterative Search Refinement, Coverage Gap Analysis, and Stopping Rules."""

from typing import Any
import uuid
from pydantic import BaseModel, Field

from research_engine.database import DatabaseManager
from research_engine.deduplication.engine import DeduplicationEngine
from research_engine.llm.client import LLMClient
from research_engine.models import (
    ConceptMap,
    PlanStatus,
    SearchPlan,
    SearchQueryPlan,
    Work,
)
from research_engine.provenance import ProvenanceTracker


class GapAnalysisOutput(BaseModel):
    coverage_gaps: list[str] = Field(description="Identified theoretical, disciplinary, or temporal coverage gaps")
    missed_vocabulary: list[str] = Field(description="Scholarly vocabulary appearing in results but missing from plan")
    stop_recommendation: bool = Field(description="Whether the stopping rule criteria have been met")
    stop_reason: str = Field(description="Explanation of stopping recommendation or remaining search budget")
    supplementary_queries: list[dict[str, Any]] = Field(
        description="Targeted queries to address remaining gaps"
    )


class SearchRefiner:
    """Analyzes search run results and produces versioned, reviewable refinement plans."""

    def __init__(self, db_manager: DatabaseManager, llm_client: LLMClient):
        self.db = db_manager
        self.llm = llm_client
        self.dedup = DeduplicationEngine(db_manager)
        self.provenance = ProvenanceTracker(db_manager)

    def analyze_and_refine(
        self,
        plan: SearchPlan,
        budget_limit: int = 5,
    ) -> tuple[GapAnalysisOutput, SearchPlan]:
        """Examine retrieved results for a plan and propose versioned supplementary queries."""
        # Retrieve works captured for this plan
        runs = self.provenance.get_run_summary(plan_id=plan.plan_id)
        total_runs_count = len(runs)

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT w.title, w.abstract, w.venue, w.publication_year
                FROM works w
                JOIN search_results sr ON w.work_id = sr.work_id
                JOIN search_runs r ON sr.run_id = r.run_id
                WHERE r.plan_id = ?
                LIMIT 50
                """,
                (plan.plan_id,),
            )
            retrieved_samples = cursor.fetchall()

        sample_titles = [f"- {r['title']} ({r['publication_year'] or 'n.d.'})" for r in retrieved_samples]
        titles_block = "\n".join(sample_titles[:30]) if sample_titles else "*No records retrieved yet*"

        system_prompt = (
            "You are an academic search methodologist conducting iterative search refinement. "
            "Analyze the retrieved literature against the original research question. "
            "Identify: 1) theoretical or disciplinary gaps, 2) uncaptured vocabulary, "
            "3) whether additional searches are warranted based on marginal returns and search budget."
        )

        user_prompt = (
            f"RESEARCH QUESTION: {plan.research_question}\n"
            f"THEORETICAL FRAMEWORK: {plan.theoretical_framework or 'Not specified'}\n"
            f"SEARCH BUDGET REMAINING: {max(0, budget_limit - total_runs_count)} runs\n"
            f"ORIGINAL CONCEPTS: {', '.join(plan.concept_map.core_concepts)}\n\n"
            f"SAMPLE OF RETRIEVED WORKS ({len(sample_titles)} total):\n{titles_block}\n"
        )

        analysis = self.llm.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=GapAnalysisOutput,
        )

        # Create versioned next-iteration search plan (v + 1)
        new_version = plan.version + 1
        new_queries = list(plan.queries)  # Retain existing queries

        for idx, q_dict in enumerate(analysis.supplementary_queries, start=1):
            q_id = f"{plan.plan_id}_v{new_version}_supp{idx}"
            new_queries.append(
                SearchQueryPlan(
                    query_id=q_id,
                    target_database=q_dict.get("target_database", "openalex"),
                    query_string=q_dict.get("query_string", ""),
                    purpose=q_dict.get("purpose", "Supplementary search to fill coverage gap"),
                    query_type="supplementary",
                    is_approved=False,  # Enforce approval gating on new queries
                )
            )

        updated_plan = SearchPlan(
            plan_id=plan.plan_id,
            version=new_version,
            research_question=plan.research_question,
            theoretical_framework=plan.theoretical_framework,
            discipline_scope=plan.discipline_scope,
            review_mode=plan.review_mode,
            concept_map=plan.concept_map,
            queries=new_queries,
            inclusion_criteria=plan.inclusion_criteria,
            exclusion_criteria=plan.exclusion_criteria,
            status=PlanStatus.DRAFT,  # Requires approval before running v2 queries
        )

        # Persist updated plan
        from research_engine.planner.generator import ResearchPlanner
        planner = ResearchPlanner(self.db, self.llm)
        planner.save_plan(updated_plan)

        return analysis, updated_plan
