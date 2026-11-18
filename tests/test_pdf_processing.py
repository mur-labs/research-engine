"""Unit tests for PDF processing and full-text retrieval workflows."""

from pathlib import Path
import pytest
import respx

from research_engine.config import ApiServiceConfig
from research_engine.database import DatabaseManager
from research_engine.deduplication.engine import DeduplicationEngine
from research_engine.models import Author, Work, RetrievalStatus
from research_engine.pdf.processor import PDFProcessor
from research_engine.retrieval.queue import RetrievalQueueManager
from research_engine.retrieval.unpaywall import UnpaywallResolver


def create_test_pdf(output_path: Path, pages_text: list[str]) -> Path:
    """Generate a minimal valid multi-page PDF with specified text pages."""
    objects: list[bytes] = []

    # 1: Catalog, 2: Pages (placeholder, filled after page objects are known)
    objects.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    objects.append(b"")  # placeholder for 2 0 obj
    # 3: Standard Helvetica font
    objects.append(b"3 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n")

    page_obj_nums: list[int] = []
    next_obj = 4
    for text in pages_text:
        page_num = next_obj
        content_num = next_obj + 1
        next_obj += 2
        page_obj_nums.append(page_num)

        stream_lines = ["BT", "/F1 11 Tf", "50 750 Td", "14 TL"]
        for line in text.splitlines() or [""]:
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            stream_lines.append(f"({escaped}) Tj T*")
        stream_lines.append("ET")
        stream_bytes = "\n".join(stream_lines).encode("latin-1", errors="replace")

        objects.append(
            f"{page_num} 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_num} 0 R >>\nendobj\n".encode("ascii")
        )
        objects.append(
            f"{content_num} 0 obj\n<< /Length {len(stream_bytes)} >>\nstream\n".encode("ascii")
            + stream_bytes
            + b"\nendstream\nendobj\n"
        )

    kids = " ".join(f"{n} 0 R" for n in page_obj_nums)
    objects[1] = f"2 0 obj\n<< /Type /Pages /Kids [{kids}] /Count {len(page_obj_nums)} >>\nendobj\n".encode("ascii")

    pdf_parts = [b"%PDF-1.4\n"]
    offsets = [0]
    for obj in objects:
        offsets.append(sum(len(p) for p in pdf_parts))
        pdf_parts.append(obj)

    xref_offset = sum(len(p) for p in pdf_parts)
    xref_lines = [f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode("ascii")]
    for off in offsets[1:]:
        xref_lines.append(f"{off:010d} 00000 n \n".encode("ascii"))

    trailer = (
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("ascii")

    output_path.write_bytes(b"".join(pdf_parts + xref_lines + [trailer]))
    return output_path


def test_pdf_processor_text_and_page_extraction(tmp_path: Path):
    db_file = tmp_path / "pdf_test.db"
    db_mgr = DatabaseManager(db_file)
    db_mgr.initialize_schema()

    storage_dir = tmp_path / "pdf_storage"
    processor = PDFProcessor(db_mgr, storage_dir)

    # Create a 2-page test PDF
    pdf_path = tmp_path / "sample_article.pdf"
    create_test_pdf(
        pdf_path,
        [
            "Title: Affective Polarization and Democratic Erosion\nDOI: 10.1017/apsr.2021.99\nPage 1 text here.",
            "Research Design and Empirical Methods\nWe test our hypothesis using survey data. Page 2 text.",
        ],
    )

    result = processor.process_pdf(pdf_path)
    assert result.error_message is None
    assert result.page_count == 2
    assert result.is_scanned is False
    assert len(result.pages) == 2
    assert result.pages[0].page_number == 1
    assert "Affective Polarization" in result.pages[0].text
    assert result.pages[1].page_number == 2
    assert "Empirical Methods" in result.pages[1].text
    assert len(result.file_hash) == 64  # Valid sha256


def test_pdf_processor_detects_scanned_pdf(tmp_path: Path):
    db_file = tmp_path / "pdf_scan.db"
    db_mgr = DatabaseManager(db_file)
    db_mgr.initialize_schema()

    processor = PDFProcessor(db_mgr, tmp_path / "storage")

    # Scanned PDF simulation (almost no selectable characters)
    scan_pdf = tmp_path / "scanned.pdf"
    create_test_pdf(scan_pdf, ["", "  "])

    result = processor.process_pdf(scan_pdf)
    assert result.page_count == 2
    assert result.is_scanned is True


def test_pdf_import_and_match(tmp_path: Path):
    db_file = tmp_path / "pdf_match.db"
    db_mgr = DatabaseManager(db_file)
    db_mgr.initialize_schema()
    dedup = DeduplicationEngine(db_mgr)

    work = Work(
        work_id="w_polar",
        doi="10.1017/apsr.2021.99",
        title="Affective Polarization and Democratic Erosion",
        authors=[Author(name="Jane Doe")],
        publication_year=2021,
    )
    dedup.merge_or_insert_work(work)

    processor = PDFProcessor(db_mgr, tmp_path / "storage")
    pdf_path = tmp_path / "article_match.pdf"
    create_test_pdf(
        pdf_path,
        [
            "Affective Polarization and Democratic Erosion\nDOI: 10.1017/apsr.2021.99\nAbstract: ...",
        ],
    )

    matched_work, result = processor.import_and_match_pdf(pdf_path)
    assert matched_work is not None
    assert matched_work.work_id == "w_polar"
    assert matched_work.retrieval_status == RetrievalStatus.EXTRACTION_COMPLETE

    # Verify retrieval record in SQLite
    with db_mgr.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM retrievals WHERE work_id = ?", ("w_polar",))
        ret_row = cursor.fetchone()
        assert ret_row is not None
        assert ret_row["status"] == "extraction_complete"
        assert ret_row["file_hash"] == result.file_hash


@respx.mock
def test_unpaywall_resolver_and_queue(tmp_path: Path):
    db_file = tmp_path / "unpaywall.db"
    db_mgr = DatabaseManager(db_file)
    db_mgr.initialize_schema()
    dedup = DeduplicationEngine(db_mgr)

    work = Work(
        work_id="w_oa",
        doi="10.1038/s41562-020-00123",
        title="Partisan Out-Group Animus",
        authors=[Author(name="Alex Rivera")],
        publication_year=2022,
    )
    dedup.merge_or_insert_work(work)

    # Mock Unpaywall
    respx.get("https://api.unpaywall.org/v2/10.1038/s41562-020-00123").respond(
        status_code=200,
        json={
            "is_oa": True,
            "oa_status": "gold",
            "best_oa_location": {
                "url_for_pdf": "https://nature.com/articles/sample.pdf",
                "version": "publishedVersion",
            },
        },
    )

    unpaywall = UnpaywallResolver(
        ApiServiceConfig(base_url="https://api.unpaywall.org/v2", email="test@example.com")
    )
    qm = RetrievalQueueManager(db_mgr, unpaywall)

    stats = qm.resolve_open_access_batch()
    assert stats["candidates_checked"] == 1
    assert stats["oa_locations_found"] == 1

    reloaded = dedup._load_work_by_id("w_oa")
    assert reloaded.is_oa is True
    assert reloaded.oa_url == "https://nature.com/articles/sample.pdf"
    assert reloaded.retrieval_status == RetrievalStatus.OA_LOCATION_FOUND

    # Export queue to CSV
    csv_path = tmp_path / "queue.csv"
    exported_file, count = qm.export_retrieval_queue_csv(csv_path)
    assert count == 1
    content = csv_path.read_text(encoding="utf-8")
    assert "Partisan Out-Group Animus" in content
    assert "https://nature.com/articles/sample.pdf" in content
