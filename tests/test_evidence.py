"""Unit tests for EvidenceExtractor and EvidenceVerifier."""

import json
from pathlib import Path
import pytest
import respx

from research_engine.config import LLMConfig
from research_engine.database import DatabaseManager
from research_engine.deduplication.engine import DeduplicationEngine
from research_engine.evidence.extractor import EvidenceExtractor
from research_engine.evidence.verifier import EvidenceVerifier
from research_engine.llm.client import LLMClient
from research_engine.models import Author, Work
from research_engine.pdf.processor import ExtractedPage, PDFProcessingResult


def test_evidence_verifier_passage():
    pages = [
        ExtractedPage(
            page_number=1,
            char_count=100,
            text="Introduction to democratic backsliding and affective polarization in American politics.",
        ),
        ExtractedPage(
            page_number=2,
            char_count=150,
            text="We find that partisan hostility reduces democratic norm compliance by 18 percent among voters.",
        ),
    ]
    pdf_res = PDFProcessingResult(
        file_path="mock.pdf",
        file_hash="hash",
        file_size_bytes=1000,
        page_count=2,
        pages=pages,
    )

    verifier = EvidenceVerifier()

    # Exact match on page 2
    assert verifier.verify_passage(pdf_res, page_number=2, passage="partisan hostility reduces democratic norm compliance") is True
    # Nonexistent quote on page 2
    assert verifier.verify_passage(pdf_res, page_number=2, passage="electoral fraud was prevalent") is False
    # Valid quote but wrong page number (page 1 instead of 2)
    assert verifier.verify_passage(pdf_res, page_number=1, passage="reduces democratic norm compliance") is False
    # Out of range page number
    assert verifier.verify_passage(pdf_res, page_number=5, passage="anything") is False


@respx.mock
def test_evidence_extractor_with_mock_llm(tmp_path: Path):
    db_file = tmp_path / "ev.db"
    db_mgr = DatabaseManager(db_file)
    db_mgr.initialize_schema()
    dedup = DeduplicationEngine(db_mgr)

    work = Work(
        work_id="w_polar_test",
        doi="10.1017/apsr.2021.99",
        title="Affective Polarization and Democratic Erosion",
        authors=[Author(name="Jane Doe")],
        publication_year=2021,
    )
    dedup.merge_or_insert_work(work)

    pages = [
        ExtractedPage(
            page_number=1,
            char_count=120,
            text="Research Question: Does affective polarization erode support for democratic norms in polarized legislatures?",
        ),
        ExtractedPage(
            page_number=2,
            char_count=180,
            text="Our empirical estimates indicate that out-party animus substantially lowers voter tolerance for executive constraints.",
        ),
    ]
    pdf_res = PDFProcessingResult(
        file_path="sample.pdf",
        file_hash="hash123",
        file_size_bytes=2048,
        page_count=2,
        pages=pages,
    )

    mock_llm_payload = {
        "research_objectives": "Analyze effect of affective polarization on democratic norm support.",
        "theoretical_framework": "Expressive partisanship and institutional decay.",
        "methodology": "Survey experiment and legislative roll-call analysis.",
        "sample_or_data": "N=2,400 registered voters.",
        "limitations": "Cross-sectional data limits causal identification over time.",
        "items": [
            {
                "claim_type": "author_conclusion",
                "content": "Out-party hostility weakens voter tolerance for executive constraints.",
                "page_start": 2,
                "page_end": 2,
                "supporting_passage": "out-party animus substantially lowers voter tolerance for executive constraints",
                "confidence_score": 0.95,
            },
            {
                "claim_type": "direct_quotation",
                "content": "Unverified claim that does not exist in paper text.",
                "page_start": 1,
                "page_end": 1,
                "supporting_passage": "completely fabricated sentence never printed in text",
                "confidence_score": 0.5,
            },
        ],
    }

    respx.post("http://localhost:5000/v1/chat/completions").respond(
        status_code=200,
        json={"choices": [{"message": {"content": json.dumps(mock_llm_payload)}}]},
    )

    llm = LLMClient(LLMConfig(base_url="http://localhost:5000/v1"))
    extractor = EvidenceExtractor(db_mgr, llm)

    records = extractor.extract_evidence(work, pdf_res)
    assert len(records) == 2

    # First claim: verified against page 2
    assert records[0]["page_start"] == 2
    assert records[0]["is_verified"] is True

    # Second claim: passage not found on page 1 -> marked unverified
    assert records[1]["page_start"] == 1
    assert records[1]["is_verified"] is False

    # Check evidence table query
    table_rows = extractor.get_evidence_table(work_id="w_polar_test")
    assert len(table_rows) == 2
    assert table_rows[0]["title"] == "Affective Polarization and Democratic Erosion"
