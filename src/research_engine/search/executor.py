"""Search execution orchestrator: executes approved queries and captures provenance."""

import uuid
from typing import Any
from rich.console import Console

from research_engine.config import AppConfig
from research_engine.connectors.openalex import OpenAlexConnector
from research_engine.connectors.crossref import CrossrefConnector
from research_engine.connectors.semanticscholar import SemanticScholarConnector
from research_engine.database import DatabaseManager
from research_engine.deduplication.engine import DeduplicationEngine
from research_engine.models import SearchPlan, SearchQueryPlan, SearchRun
from research_engine.provenance import ProvenanceTracker

console = Console()


class SearchExecutor:
    """Coordinates API connectors, query approval checks, deduplication, and provenance tracking."""

    def __init__(self, db_manager: DatabaseManager, config: AppConfig):
        self.db = db_manager
        self.config = config
        self.dedup = DeduplicationEngine(db_manager)
        self.provenance = ProvenanceTracker(db_manager)

        # Initialize connectors
        self.connectors = {
            "openalex": OpenAlexConnector(
                base_url=config.apis.openalex.base_url,
                email=config.apis.openalex.email,
                rate_limit_per_second=config.apis.openalex.rate_limit_per_second,
            ),
            "crossref": CrossrefConnector(
                base_url=config.apis.crossref.base_url,
                email=config.apis.crossref.email,
                rate_limit_per_second=config.apis.crossref.rate_limit_per_second,
            ),
            "semanticscholar": SemanticScholarConnector(
                base_url=config.apis.semanticscholar.base_url,
                api_key=config.apis.semanticscholar.api_key,
                rate_limit_per_second=config.apis.semanticscholar.rate_limit_per_second,
            ),
        }

    def execute_plan(
        self,
        plan: SearchPlan,
        limit_per_query: int = 25,
        target_query_ids: list[str] | None = None,
    ) -> list[SearchRun]:
        """Execute only APPROVED queries from the provided SearchPlan."""
        # Safety gate: Filter approved queries
        queries_to_run: list[SearchQueryPlan] = []
        for q in plan.queries:
            if not q.is_approved:
                continue
            if target_query_ids and q.query_id not in target_query_ids:
                continue
            queries_to_run.append(q)

        if not queries_to_run:
            raise ValueError(
                f"No approved queries found to execute for plan {plan.plan_id}. "
                "Run 'research-engine plan approve' first."
            )

        runs: list[SearchRun] = []

        for q in queries_to_run:
            connector = self.connectors.get(q.target_database.lower())
            if not connector:
                console.print(f"[yellow]Warning: No connector registered for '{q.target_database}'. Skipping.[/yellow]")
                continue

            run_id = f"run_{uuid.uuid4().hex[:10]}"
            error_msg: str | None = None
            total_found = 0
            records_retrieved = 0
            new_records = 0
            run_recorded = False

            try:
                # Query connector
                result = connector.search(
                    query=q.query_string,
                    limit=limit_per_query,
                    filters=q.filters,
                )
                total_found = result.total_found
                records_retrieved = len(result.works)

                # 1. Record search run first to satisfy FOREIGN KEY in search_results
                self.provenance.record_search_run(
                    run_id=run_id,
                    plan_id=plan.plan_id,
                    plan_version=plan.version,
                    query_id=q.query_id,
                    target_database=q.target_database,
                    query_string=q.query_string,
                    total_results=total_found,
                    records_retrieved=records_retrieved,
                    new_records=0,
                    error_message=None,
                )
                run_recorded = True

                # 2. Process results through deduplication engine
                for w in result.works:
                    saved_work, is_new = self.dedup.merge_or_insert_work(w)
                    if is_new:
                        new_records += 1

                    # Record individual result link in search_results table
                    result_id = f"res_{uuid.uuid4().hex[:12]}"
                    self.provenance.record_search_result(
                        result_id=result_id,
                        run_id=run_id,
                        work_id=saved_work.work_id,
                        raw_payload=w.raw_metadata,
                    )

                # Update search run with actual new_records_added count
                with self.db.get_connection() as conn:
                    conn.execute(
                        "UPDATE search_runs SET new_records_added = ? WHERE run_id = ?",
                        (new_records, run_id),
                    )

            except Exception as exc:
                error_msg = str(exc)
                console.print(f"[bold red]Error executing query {q.query_id}:[/bold red] {exc}")
                # Record or update failed search run
                if run_recorded:
                    with self.db.get_connection() as conn:
                        conn.execute(
                            "UPDATE search_runs SET error_message = ?, new_records_added = ? WHERE run_id = ?",
                            (error_msg, new_records, run_id),
                        )
                else:
                    self.provenance.record_search_run(
                        run_id=run_id,
                        plan_id=plan.plan_id,
                        plan_version=plan.version,
                        query_id=q.query_id,
                        target_database=q.target_database,
                        query_string=q.query_string,
                        total_results=total_found,
                        records_retrieved=records_retrieved,
                        new_records=new_records,
                        error_message=error_msg,
                    )

            run_obj = SearchRun(
                run_id=run_id,
                plan_id=plan.plan_id,
                plan_version=plan.version,
                target_database=q.target_database,
                query_string=q.query_string,
                total_results_found=total_found,
                records_retrieved=records_retrieved,
                new_records_added=new_records,
                error_message=error_msg,
            )
            runs.append(run_obj)

        return runs
