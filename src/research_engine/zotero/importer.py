"""Zotero BibTeX staging manager: links research works and exports unimported records."""

from pathlib import Path
from typing import Any
from rich.console import Console

from research_engine.database import DatabaseManager
from research_engine.deduplication.engine import DeduplicationEngine
from research_engine.export.exporters import export_works_to_bibtex
from research_engine.models import Work, RetrievalStatus
from research_engine.zotero.reader import LocalZoteroReader

console = Console()


class ZoteroStagingManager:
    """Matches scholarly works against local Zotero library and stages clean BibTeX files."""

    def __init__(self, db_manager: DatabaseManager, zotero_reader: LocalZoteroReader, export_dir: Path | str):
        self.db = db_manager
        self.reader = zotero_reader
        self.export_dir = Path(export_dir)
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.dedup = DeduplicationEngine(db_manager)

    def sync_local_status(self) -> dict[str, int]:
        """Cross-reference works in Research Engine against local Zotero library and update zotero_key and retrieval_status."""
        if not self.reader.is_available():
            raise FileNotFoundError(f"Zotero SQLite not accessible at {self.reader.sqlite_path}")

        matched_count = 0
        has_pdf_count = 0
        total_works = 0

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT work_id FROM works")
            work_ids = [r["work_id"] for r in cursor.fetchall()]

        total_works = len(work_ids)

        for w_id in work_ids:
            work = self.dedup._load_work_by_id(w_id)
            if not work:
                continue

            zotero_item = None
            if work.doi:
                zotero_item = self.reader.find_item_by_doi(work.doi)
            if not zotero_item and work.title:
                zotero_item = self.reader.find_item_by_title(work.title)

            if zotero_item:
                matched_count += 1
                new_retrieval_status = work.retrieval_status
                if zotero_item.has_pdf:
                    has_pdf_count += 1
                    new_retrieval_status = RetrievalStatus.FULL_TEXT_AVAILABLE

                with self.db.get_connection() as conn:
                    conn.execute(
                        """
                        UPDATE works
                        SET zotero_key = ?, retrieval_status = ?
                        WHERE work_id = ?
                        """,
                        (zotero_item.key, new_retrieval_status.value, w_id),
                    )

        return {
            "total_works": total_works,
            "matched_in_zotero": matched_count,
            "with_pdf_in_zotero": has_pdf_count,
            "missing_from_zotero": total_works - matched_count,
        }

    def stage_bibtex_import(
        self,
        collection_tag: str = "ResearchEngine",
        output_filename: str = "staged_import.bib",
        only_unlinked: bool = True,
    ) -> tuple[Path, int]:
        """Export candidate works to a BibTeX staging file formatted for clean Zotero import."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            if only_unlinked:
                cursor.execute("SELECT work_id FROM works WHERE zotero_key IS NULL")
            else:
                cursor.execute("SELECT work_id FROM works")
            work_ids = [r["work_id"] for r in cursor.fetchall()]

        works = [self.dedup._load_work_by_id(w_id) for w_id in work_ids]
        valid_works = [w for w in works if w is not None]

        output_path = self.export_dir / output_filename
        export_works_to_bibtex(valid_works, output_path)

        return output_path, len(valid_works)
