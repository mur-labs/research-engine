"""Comprehensive research synthesis and PRISMA audit report generator."""

from datetime import datetime
from pathlib import Path
from typing import Any
from research_engine.database import DatabaseManager
from research_engine.models import SearchPlan
from research_engine.provenance import ProvenanceTracker


class ResearchReportGenerator:
    """Produces reproducible, traceable markdown reports documenting the complete research cycle."""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self.provenance = ProvenanceTracker(db_manager)

    def generate_report(self, plan: SearchPlan, output_path: Path | str | None = None) -> str:
        """Compile end-to-end research report with search accounting, full-text status, and verified evidence."""
        # 1. Search runs summary
        runs = self.provenance.get_run_summary(plan_id=plan.plan_id)
        total_runs = len(runs)
        total_retrieved = sum(r["records_retrieved"] for r in runs)
        total_unique_added = sum(r["new_records_added"] for r in runs)

        # 2. Database statistics
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM works")
            total_works_db = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM works WHERE retrieval_status IN ('full_text_available', 'extraction_complete')")
            full_texts_accessible = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM works WHERE zotero_key IS NOT NULL")
            zotero_linked = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM evidence_records")
            total_evidence_claims = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM evidence_records WHERE is_verified = 1")
            verified_evidence_claims = cursor.fetchone()[0]

            # Fetch top evidence records
            cursor.execute(
                """
                SELECT e.claim_type, e.content, e.page_start, e.supporting_passage,
                       e.is_verified, w.title, w.doi
                FROM evidence_records e
                JOIN works w ON e.work_id = w.work_id
                ORDER BY e.is_verified DESC, e.created_at DESC
                LIMIT 20
                """
            )
            evidence_rows = cursor.fetchall()

        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        lines = [
            f"# Academic Research Synthesis: {plan.research_question}",
            "",
            f"- **Plan ID:** `{plan.plan_id}` (v{plan.version})",
            f"- **Theoretical Framework:** {plan.theoretical_framework or 'Multidisciplinary framework'}",
            f"- **Discipline Scope:** {plan.discipline_scope or 'Political Science and Public Administration'}",
            f"- **Review Mode:** {plan.review_mode.value.capitalize()}",
            f"- **Report Generated At:** {now_str}",
            "",
            "## 1. Search Strategy & Execution Accounting (PRISMA Flow)",
            "",
            "| Database | Query | Total Found | Retrieved | New Unique | Status |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ]

        for r in runs:
            status_disp = "✓ Success" if not r["error_message"] else f"✗ Error: {r['error_message']}"
            q_disp = r["query_string"].replace("|", "\\|")
            lines.append(
                f"| `{r['target_database']}` | `{q_disp}` | {r['total_results_found']} | {r['records_retrieved']} | {r['new_records_added']} | {status_disp} |"
            )

        lines.extend([
            "",
            f"- **Total Search Runs Executed:** {total_runs}",
            f"- **Gross Records Retrieved:** {total_retrieved}",
            f"- **Deduplicated Corpus in Database:** {total_works_db} unique records",
            f"- **Records Linked to Zotero:** {zotero_linked}",
            f"- **Full-Text PDFs Acquired & Processed:** {full_texts_accessible}",
            "",
            "## 2. Concept Mapping & Theoretical Grounding",
            "",
            "### Core Concepts",
        ])

        for c in plan.concept_map.core_concepts:
            syns = plan.concept_map.synonyms.get(c, [])
            syn_str = ", ".join(f"`{s}`" for s in syns) if syns else "*None*"
            lines.append(f"- **{c}**: {syn_str}")

        lines.extend([
            "",
            "### Related Concepts (Non-Equivalent)",
        ])
        for rc in plan.concept_map.related_concepts:
            lines.append(f"- {rc}")

        lines.extend([
            "",
            "### Competing Theoretical Explanations",
        ])
        for ce in plan.concept_map.competing_explanations:
            lines.append(f"- {ce}")

        lines.extend([
            "",
            "## 3. Evidence Synthesis & Verified Findings",
            "",
            f"**Total Claims Extracted:** {total_evidence_claims} | **Verbatim Verified in Full Text:** {verified_evidence_claims}",
            "",
            "| Type | Claim / Finding | Page | Verified | Source Article |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ])

        if evidence_rows:
            for er in evidence_rows:
                ver_badge = "✓ YES" if er["is_verified"] else "⚠ UNVERIFIED"
                lines.append(
                    f"| {er['claim_type']} | {er['content']} | p. {er['page_start']} | {ver_badge} | *{er['title']}* |"
                )
        else:
            lines.append("| — | *No evidence records extracted yet* | — | — | — |")

        lines.extend([
            "",
            "## 4. Methodological Limitations & Provenance Notice",
            "",
            "1. **Access Boundaries:** Searches represent coverage across OpenAlex, Crossref, Semantic Scholar, and Unpaywall. Documents requiring non-automated institutional authentication are tracked in the retrieval queue.",
            "2. **Deduplication Precedence:** Records were deduplicated with normalized DOI taking highest precedence, followed by source IDs and title/author/year fuzzy matching.",
            "3. **Claim Attribution:** Every verified empirical finding is anchored to an exact 1-indexed document page and verified passage.",
            "",
            "---",
            "*Report compiled automatically by Antigravity AI-Powered Academic Research Engine.*",
        ])

        content = "\n".join(lines) + "\n"

        if output_path:
            p = Path(output_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")

        return content
