"""pypdf PDF processor: extracts page structure, detects scanned documents, and hashes files."""

import hashlib
from pathlib import Path
from typing import Any
from pypdf import PdfReader
from pydantic import BaseModel, Field

from research_engine.database import DatabaseManager
from research_engine.deduplication.engine import DeduplicationEngine
from research_engine.models import Work, RetrievalStatus


class ExtractedPage(BaseModel):
    page_number: int  # 1-indexed
    char_count: int
    text: str


class PDFProcessingResult(BaseModel):
    file_path: str
    file_hash: str
    file_size_bytes: int
    page_count: int
    is_scanned: bool = False
    pages: list[ExtractedPage] = Field(default_factory=list)
    total_characters: int = 0
    error_message: str | None = None


class PDFProcessor:
    """Processes PDF files, extracts page text, detects scans, and updates retrievals table."""

    def __init__(self, db_manager: DatabaseManager, pdf_storage_dir: Path | str, max_size_mb: float = 50.0):
        self.db = db_manager
        self.storage_dir = Path(pdf_storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.max_size_bytes = int(max_size_mb * 1024 * 1024)
        self.dedup = DeduplicationEngine(db_manager)

    @staticmethod
    def compute_sha256(file_path: Path | str) -> str:
        """Compute SHA-256 hash of a file for duplicate detection."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    def process_pdf(self, file_path: Path | str) -> PDFProcessingResult:
        """Extract text and metadata from a PDF file using pypdf."""
        path = Path(file_path)
        if not path.is_file():
            return PDFProcessingResult(
                file_path=str(path),
                file_hash="",
                file_size_bytes=0,
                page_count=0,
                error_message=f"File not found: {path}",
            )

        file_size = path.stat().st_size
        if file_size > self.max_size_bytes:
            return PDFProcessingResult(
                file_path=str(path),
                file_hash="",
                file_size_bytes=file_size,
                page_count=0,
                error_message=f"File exceeds maximum allowed size ({file_size} bytes > {self.max_size_bytes} bytes)",
            )

        file_hash = self.compute_sha256(path)

        try:
            reader = PdfReader(str(path))
            pages: list[ExtractedPage] = []
            total_chars = 0

            for page_idx, page in enumerate(reader.pages):
                text = (page.extract_text() or "").strip()
                char_count = len(text)
                total_chars += char_count
                pages.append(
                    ExtractedPage(
                        page_number=page_idx + 1,  # 1-indexed
                        char_count=char_count,
                        text=text,
                    )
                )
        except Exception as exc:
            return PDFProcessingResult(
                file_path=str(path),
                file_hash=file_hash,
                file_size_bytes=file_size,
                page_count=0,
                error_message=f"Corrupt or unreadable PDF: {exc}",
            )

        page_count = len(pages)
        # If document has pages but average characters per page < 50, likely scanned / image-only
        avg_chars = (total_chars / page_count) if page_count > 0 else 0
        is_scanned = page_count > 0 and avg_chars < 50

        return PDFProcessingResult(
            file_path=str(path),
            file_hash=file_hash,
            file_size_bytes=file_size,
            page_count=page_count,
            is_scanned=is_scanned,
            pages=pages,
            total_characters=total_chars,
        )

    def import_and_match_pdf(
        self,
        pdf_file: Path | str,
        target_work_id: str | None = None,
    ) -> tuple[Work | None, PDFProcessingResult]:
        """Import PDF, extract text, match to scholarly work, and record retrieval provenance."""
        path = Path(pdf_file)
        result = self.process_pdf(path)

        import uuid

        retrieval_id = f"ret_{uuid.uuid4().hex[:12]}"
        matched_work: Work | None = None

        if target_work_id:
            matched_work = self.dedup._load_work_by_id(target_work_id)
        else:
            # Try to match by DOI or title in first 2 pages
            if result.pages:
                first_text = " ".join(p.text for p in result.pages[:2])
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT work_id, doi, title FROM works")
                    rows = cursor.fetchall()
                    for r in rows:
                        doi = r["doi"]
                        title = r["title"]
                        if doi and doi.lower() in first_text.lower():
                            matched_work = self.dedup._load_work_by_id(r["work_id"])
                            break
                        if title and len(title) > 20 and title.lower() in first_text.lower():
                            matched_work = self.dedup._load_work_by_id(r["work_id"])
                            break

        if matched_work:
            new_status = (
                RetrievalStatus.EXTRACTION_COMPLETE
                if not result.is_scanned and result.error_message is None
                else (RetrievalStatus.EXTRACTION_FAILED if result.error_message else RetrievalStatus.FULL_TEXT_AVAILABLE)
            )

            with self.db.get_connection() as conn:
                # Record retrieval
                conn.execute(
                    """
                    INSERT INTO retrievals (
                        retrieval_id, work_id, status, source_url, file_path,
                        file_hash, file_size_bytes, error_message, attempted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        retrieval_id,
                        matched_work.work_id,
                        new_status.value,
                        None,
                        str(path.resolve()),
                        result.file_hash,
                        result.file_size_bytes,
                        result.error_message,
                    ),
                )
                # Update work retrieval status
                conn.execute(
                    "UPDATE works SET retrieval_status = ? WHERE work_id = ?",
                    (new_status.value, matched_work.work_id),
                )

            matched_work = self.dedup._load_work_by_id(matched_work.work_id)

        return matched_work, result
