"""Read-only local Zotero SQLite inspector for identifying existing items and PDF attachments."""

from pathlib import Path
import sqlite3
from typing import Any
from pydantic import BaseModel

from research_engine.connectors.base import clean_doi
from research_engine.deduplication.engine import normalize_title


class ZoteroItemSummary(BaseModel):
    item_id: int
    key: str
    doi: str | None = None
    title: str | None = None
    has_pdf: bool = False
    pdf_path: str | None = None


class LocalZoteroReader:
    """Safely inspects local Zotero SQLite database in read-only mode."""

    def __init__(self, zotero_data_dir: Path | str):
        self.data_dir = Path(zotero_data_dir)
        self.sqlite_path = self.data_dir / "zotero.sqlite"
        self.storage_dir = self.data_dir / "storage"

    def is_available(self) -> bool:
        """Check if local zotero.sqlite file exists."""
        return self.sqlite_path.is_file()

    def get_connection(self) -> sqlite3.Connection:
        """Open a strictly READ-ONLY SQLite connection using the URI format."""
        if not self.is_available():
            raise FileNotFoundError(f"Zotero database not found at {self.sqlite_path}")
        uri = f"file:{self.sqlite_path.resolve()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def get_library_summary(self) -> dict[str, Any]:
        """Return total counts of items and PDF attachments in local Zotero library."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM items WHERE itemTypeID NOT IN (SELECT itemTypeID FROM itemTypes WHERE typeName IN ('attachment', 'note'))")
            total_regular_items = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM itemAttachments WHERE contentType = 'application/pdf'")
            total_pdfs = cursor.fetchone()[0]

        return {
            "sqlite_path": str(self.sqlite_path),
            "storage_dir": str(self.storage_dir),
            "total_regular_items": total_regular_items,
            "total_pdf_attachments": total_pdfs,
        }

    def find_item_by_doi(self, doi: str) -> ZoteroItemSummary | None:
        """Find Zotero item by exact normalized DOI and check if it has a PDF attachment."""
        cleaned = clean_doi(doi)
        if not cleaned:
            return None

        query = """
            SELECT i.itemID, i.key, id.value AS doi_val
            FROM items i
            JOIN itemData id ON i.itemID = id.itemID
            JOIN fields f ON id.fieldID = f.fieldID
            WHERE f.fieldName = 'DOI'
              AND LOWER(TRIM(id.value)) IN (?, ?, ?, ?)
            LIMIT 1
        """
        candidates = (
            cleaned,
            f"https://doi.org/{cleaned}",
            f"http://doi.org/{cleaned}",
            f"doi:{cleaned}",
        )
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, candidates)
            row = cursor.fetchone()
            if not row:
                return None

            item_id = row["itemID"]
            item_key = row["key"]

            # Check PDF attachment
            has_pdf, pdf_path = self._get_attachment_info(conn, item_id)

            # Get title
            title = self._get_item_title(conn, item_id)

            return ZoteroItemSummary(
                item_id=item_id,
                key=item_key,
                doi=cleaned,
                title=title,
                has_pdf=has_pdf,
                pdf_path=pdf_path,
            )

    def find_item_by_title(self, title: str) -> ZoteroItemSummary | None:
        """Find Zotero item by normalized title."""
        norm_target = normalize_title(title)
        if not norm_target or len(norm_target) < 15:
            return None

        query = """
            SELECT i.itemID, i.key, id.value AS title_val
            FROM items i
            JOIN itemData id ON i.itemID = id.itemID
            JOIN fields f ON id.fieldID = f.fieldID
            WHERE f.fieldName = 'title'
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            for row in cursor.fetchall():
                if normalize_title(row["title_val"]) == norm_target:
                    item_id = row["itemID"]
                    has_pdf, pdf_path = self._get_attachment_info(conn, item_id)
                    return ZoteroItemSummary(
                        item_id=item_id,
                        key=row["key"],
                        title=row["title_val"],
                        has_pdf=has_pdf,
                        pdf_path=pdf_path,
                    )
        return None

    def _get_attachment_info(self, conn: sqlite3.Connection, parent_item_id: int) -> tuple[bool, str | None]:
        """Check if parent item has a PDF attachment and resolve path if possible."""
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT ia.itemID, ia.path, i.key
            FROM itemAttachments ia
            JOIN items i ON ia.itemID = i.itemID
            WHERE ia.parentItemID = ? AND ia.contentType = 'application/pdf'
            LIMIT 1
            """,
            (parent_item_id,),
        )
        row = cursor.fetchone()
        if not row:
            return False, None

        raw_path = row["path"]
        attach_key = row["key"]

        # If stored under Zotero storage (storage:filename.pdf)
        if raw_path and raw_path.startswith("storage:"):
            filename = raw_path[len("storage:"):]
            resolved = self.storage_dir / attach_key / filename
            return True, str(resolved) if resolved.is_file() else None
        elif raw_path:
            p = Path(raw_path)
            return True, str(p) if p.is_file() else None

        return True, None

    def _get_item_title(self, conn: sqlite3.Connection, item_id: int) -> str | None:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id.value
            FROM itemData id
            JOIN fields f ON id.fieldID = f.fieldID
            WHERE id.itemID = ? AND f.fieldName = 'title'
            LIMIT 1
            """,
            (item_id,),
        )
        row = cursor.fetchone()
        return row[0] if row else None
