"""Retrieval Queue Manager: Identifies papers requiring manual institutional acquisition and resolves OA."""

import csv
from pathlib import Path
from typing import Any
from rich.console import Console

from research_engine.database import DatabaseManager
from research_engine.deduplication.engine import DeduplicationEngine
from research_engine.models import Work, RetrievalStatus
from research_engine.retrieval.unpaywall import UnpaywallResolver

console = Console()


class RetrievalQueueManager:
    """Manages the full-text acquisition queue, distinguishing OA from institutional access."""

    def __init__(self, db_manager: DatabaseManager, unpaywall: UnpaywallResolver | None = None):
        self.db = db_manager
        self.unpaywall = unpaywall
        self.dedup = DeduplicationEngine(db_manager)

    def get_retrieval_candidates(self, only_missing: bool = True) -> list[Work]:
        """Fetch papers requiring full text."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            if only_missing:
                cursor.execute(
                    """
                    SELECT work_id FROM works
                    WHERE retrieval_status NOT IN ('full_text_available', 'extraction_complete', 'excluded')
                    ORDER BY publication_year DESC, citation_count DESC
                    """
                )
            else:
                cursor.execute("SELECT work_id FROM works ORDER BY publication_year DESC")

            work_ids = [r["work_id"] for r in cursor.fetchall()]

        works = [self.dedup._load_work_by_id(w_id) for w_id in work_ids]
        return [w for w in works if w is not None]

    def resolve_open_access_batch(self) -> dict[str, int]:
        """Query Unpaywall for pending works with DOIs and update their retrieval status and OA URLs."""
        if not self.unpaywall:
            raise ValueError("Unpaywall resolver is not configured.")

        candidates = self.get_retrieval_candidates(only_missing=True)
        resolved_oa_count = 0
        checked_count = 0

        for work in candidates:
            if not work.doi:
                continue

            checked_count += 1
            res = self.unpaywall.resolve_doi(work.doi)
            if res.is_oa and res.oa_url:
                resolved_oa_count += 1
                with self.db.get_connection() as conn:
                    conn.execute(
                        """
                        UPDATE works
                        SET is_oa = 1, oa_url = ?, retrieval_status = 'oa_location_found'
                        WHERE work_id = ?
                        """,
                        (res.oa_url, work.work_id),
                    )

        return {
            "candidates_checked": checked_count,
            "oa_locations_found": resolved_oa_count,
        }

    def export_retrieval_queue_csv(self, output_path: Path | str) -> tuple[Path, int]:
        """Export a structured acquisition queue for the researcher."""
        candidates = self.get_retrieval_candidates(only_missing=True)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "work_id",
            "title",
            "authors",
            "year",
            "doi",
            "venue",
            "landing_page_url",
            "oa_url",
            "retrieval_status",
            "zotero_key",
        ]

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for w in candidates:
                authors_str = "; ".join(a.name for a in w.authors)
                writer.writerow(
                    {
                        "work_id": w.work_id,
                        "title": w.title,
                        "authors": authors_str,
                        "year": w.publication_year or "",
                        "doi": w.doi or "",
                        "venue": w.venue or "",
                        "landing_page_url": w.landing_page_url or (f"https://doi.org/{w.doi}" if w.doi else ""),
                        "oa_url": w.oa_url or "",
                        "retrieval_status": w.retrieval_status.value,
                        "zotero_key": w.zotero_key or "",
                    }
                )

        return path, len(candidates)
