"""Unit tests for LocalZoteroReader and ZoteroStagingManager."""

from pathlib import Path
import sqlite3
import pytest

from research_engine.database import DatabaseManager
from research_engine.deduplication.engine import DeduplicationEngine
from research_engine.models import Author, Work, RetrievalStatus
from research_engine.zotero.reader import LocalZoteroReader
from research_engine.zotero.importer import ZoteroStagingManager


def create_mock_zotero_db(db_path: Path, storage_path: Path):
    """Create a minimal mock Zotero SQLite database structure for isolated testing."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.executescript(
        """
        CREATE TABLE items (itemID INTEGER PRIMARY KEY, itemTypeID INTEGER, key TEXT);
        CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
        CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
        CREATE TABLE itemData (itemID INTEGER, fieldID INTEGER, value TEXT);
        CREATE TABLE itemAttachments (
            itemID INTEGER PRIMARY KEY,
            parentItemID INTEGER,
            contentType TEXT,
            path TEXT
        );

        INSERT INTO itemTypes VALUES (1, 'journalArticle'), (2, 'attachment'), (3, 'note');
        INSERT INTO fields VALUES (1, 'title'), (2, 'DOI');

        -- Item 1: Has DOI and PDF attachment
        INSERT INTO items VALUES (101, 1, 'KEY00101');
        INSERT INTO itemData VALUES (101, 1, 'Affective Polarization in Modern Democracies');
        INSERT INTO itemData VALUES (101, 2, '10.1017/sample.123');
        -- Attachment Item 201
        INSERT INTO items VALUES (201, 2, 'KEY00201');
        INSERT INTO itemAttachments VALUES (201, 101, 'application/pdf', 'storage:article.pdf');

        -- Item 2: Has Title match only, NO PDF
        INSERT INTO items VALUES (102, 1, 'KEY00102');
        INSERT INTO itemData VALUES (102, 1, 'Democratic Backsliding and Partisan Hostility');
        INSERT INTO itemData VALUES (102, 2, '10.1111/other.456');
        """
    )
    conn.commit()
    conn.close()

    # Create dummy storage file for Item 201 (keyed by attachment key KEY00201)
    item_storage = storage_path / "KEY00201"
    item_storage.mkdir(parents=True, exist_ok=True)
    (item_storage / "article.pdf").write_bytes(b"%PDF-1.4 Mock PDF Content")


def test_local_zotero_reader(tmp_path: Path):
    zotero_dir = tmp_path / "zotero_mock"
    zotero_dir.mkdir()
    storage_dir = zotero_dir / "storage"
    storage_dir.mkdir()
    db_file = zotero_dir / "zotero.sqlite"

    create_mock_zotero_db(db_file, storage_dir)

    reader = LocalZoteroReader(zotero_dir)
    assert reader.is_available() is True

    summary = reader.get_library_summary()
    assert summary["total_regular_items"] == 2
    assert summary["total_pdf_attachments"] == 1

    # Find item by DOI
    found_doi = reader.find_item_by_doi("10.1017/sample.123")
    assert found_doi is not None
    assert found_doi.key == "KEY00101"
    assert found_doi.has_pdf is True
    assert found_doi.pdf_path is not None
    assert Path(found_doi.pdf_path).is_file()

    # Find item by Title (no PDF)
    found_title = reader.find_item_by_title("Democratic Backsliding & Partisan Hostility")
    assert found_title is not None
    assert found_title.key == "KEY00102"
    assert found_title.has_pdf is False


def test_zotero_staging_manager(tmp_path: Path):
    # Setup mock Zotero
    zotero_dir = tmp_path / "zotero_mock"
    zotero_dir.mkdir()
    storage_dir = zotero_dir / "storage"
    storage_dir.mkdir()
    db_file = zotero_dir / "zotero.sqlite"
    create_mock_zotero_db(db_file, storage_dir)
    reader = LocalZoteroReader(zotero_dir)

    # Setup research engine DB
    re_db_file = tmp_path / "re.db"
    db_mgr = DatabaseManager(re_db_file)
    db_mgr.initialize_schema()
    dedup = DeduplicationEngine(db_mgr)

    # Add 2 works into research DB: 1 matches Zotero, 1 is new
    w1 = Work(
        work_id="w1",
        doi="10.1017/sample.123",
        title="Affective Polarization in Modern Democracies",
        authors=[Author(name="Jane Doe")],
        publication_year=2021,
    )
    w2 = Work(
        work_id="w2",
        doi="10.9999/unlinked.789",
        title="Completely New Unlinked Work",
        authors=[Author(name="John Smith")],
        publication_year=2024,
    )
    dedup.merge_or_insert_work(w1)
    dedup.merge_or_insert_work(w2)

    export_dir = tmp_path / "exports"
    staging = ZoteroStagingManager(db_mgr, reader, export_dir)

    # Cross-reference
    stats = staging.sync_local_status()
    assert stats["total_works"] == 2
    assert stats["matched_in_zotero"] == 1
    assert stats["with_pdf_in_zotero"] == 1
    assert stats["missing_from_zotero"] == 1

    # Check updated work status
    reloaded_w1 = dedup._load_work_by_id("w1")
    assert reloaded_w1.zotero_key == "KEY00101"
    assert reloaded_w1.retrieval_status == RetrievalStatus.FULL_TEXT_AVAILABLE

    # Stage unlinked import
    staged_file, count = staging.stage_bibtex_import(output_filename="unlinked.bib")
    assert count == 1
    assert staged_file.is_file()
    content = staged_file.read_text(encoding="utf-8")
    assert "Completely New Unlinked Work" in content
    assert "Affective Polarization" not in content  # Already linked, excluded from unlinked staging


def test_zotero_doi_lookup_exact_match_only(tmp_path: Path):
    zotero_dir = tmp_path / "zotero"
    zotero_dir.mkdir()
    storage_dir = zotero_dir / "storage"
    storage_dir.mkdir()
    create_mock_zotero_db(zotero_dir / "zotero.sqlite", storage_dir)
    reader = LocalZoteroReader(zotero_dir)
    # Mock DB contains 10.1017/sample.123; a prefix like 10.1017/sample.1 must NOT match
    assert reader.find_item_by_doi("10.1017/sample.1") is None
    assert reader.find_item_by_doi("https://doi.org/10.1017/sample.123") is not None
