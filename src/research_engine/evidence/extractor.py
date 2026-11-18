"""Structured Evidence Extractor: extracts findings, methodology, and verified passage links."""

import uuid
from typing import Any
from pydantic import BaseModel, Field

from research_engine.database import DatabaseManager
from research_engine.evidence.verifier import EvidenceVerifier
from research_engine.llm.client import LLMClient
from research_engine.models import EvidenceType, Work
from research_engine.pdf.processor import PDFProcessingResult


class RawEvidenceItem(BaseModel):
    claim_type: EvidenceType = Field(description="Category: direct_quotation, faithful_paraphrase, author_conclusion, engine_interpretation")
    content: str = Field(description="Extracted finding, theoretical claim, or methodological detail")
    page_start: int = Field(description="1-indexed starting page in the document where this claim appears")
    page_end: int = Field(description="1-indexed ending page")
    supporting_passage: str = Field(description="Exact verbatim excerpt from the document supporting this claim")
    confidence_score: float = Field(default=1.0, description="Confidence score from 0.0 to 1.0")


class RawEvidenceExtraction(BaseModel):
    research_objectives: str = Field(description="Stated research question or objectives")
    theoretical_framework: str = Field(description="Theoretical framework or theoretical mechanisms tested")
    methodology: str = Field(description="Research design, method, and empirical data")
    sample_or_data: str = Field(description="Sample size, geographic coverage, or dataset description")
    limitations: str = Field(description="Limitations noted by the authors")
    items: list[RawEvidenceItem] = Field(description="List of specific claims with page-level citations")


class EvidenceExtractor:
    """Coordinates LLM extraction and deterministic passage verification against PDF text."""

    def __init__(self, db_manager: DatabaseManager, llm_client: LLMClient):
        self.db = db_manager
        self.llm = llm_client
        self.verifier = EvidenceVerifier()

    def extract_evidence(
        self,
        work: Work,
        pdf_result: PDFProcessingResult,
        research_question: str | None = None,
    ) -> list[dict[str, Any]]:
        """Extract structured evidence from processed PDF pages, verify citations, and persist records."""
        if not pdf_result.pages or pdf_result.is_scanned:
            raise ValueError(f"Cannot extract evidence from unreadable or scanned PDF (work_id: {work.work_id})")

        # Compile document text with explicit page markers
        doc_chunks = []
        for p in pdf_result.pages:
            doc_chunks.append(f"--- PAGE {p.page_number} ---\n{p.text}")
        full_doc_text = "\n\n".join(doc_chunks)

        # Truncate if document is excessively long (to protect context limits)
        if len(full_doc_text) > 80000:
            full_doc_text = full_doc_text[:80000] + "\n\n[TRUNCATED]"

        system_prompt = (
            "You are a rigorous scholarly evidence extractor for systematic literature reviews. "
            "Your task is to extract empirical findings, theoretical frameworks, and research design details. "
            "CRITICAL RULES:\n"
            "1. NEVER invent or hallucinate claims or quotations.\n"
            "2. For every claim, provide the EXACT verbatim passage and 1-indexed PAGE NUMBER where it appears.\n"
            "3. Categorize claims accurately as 'direct_quotation', 'faithful_paraphrase', or 'author_conclusion'.\n"
        )

        user_prompt = (
            f"DOCUMENT TITLE: {work.title}\n"
            f"AUTHORS: {', '.join(a.name for a in work.authors)}\n"
            f"REVIEW FOCUS: {research_question or 'Multidisciplinary empirical synthesis'}\n\n"
            f"FULL DOCUMENT WITH PAGE LABELS:\n{full_doc_text}"
        )

        extraction = self.llm.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=RawEvidenceExtraction,
        )

        saved_records = []

        with self.db.get_connection() as conn:
            # Delete any previous evidence records for this work to allow clean re-runs
            conn.execute("DELETE FROM evidence_records WHERE work_id = ?", (work.work_id,))

            for item in extraction.items:
                ev_id = f"ev_{uuid.uuid4().hex[:12]}"
                # Verify quote deterministically against the PDF structure
                is_verified = self.verifier.verify_passage(
                    pdf_result=pdf_result,
                    page_number=item.page_start,
                    passage=item.supporting_passage,
                )

                conn.execute(
                    """
                    INSERT INTO evidence_records (
                        evidence_id, work_id, claim_type, content, page_start,
                        page_end, supporting_passage, confidence_score, is_verified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ev_id,
                        work.work_id,
                        item.claim_type.value,
                        item.content,
                        item.page_start,
                        item.page_end,
                        item.supporting_passage,
                        item.confidence_score,
                        1 if is_verified else 0,
                    ),
                )

                saved_records.append(
                    {
                        "evidence_id": ev_id,
                        "work_id": work.work_id,
                        "claim_type": item.claim_type.value,
                        "content": item.content,
                        "page_start": item.page_start,
                        "page_end": item.page_end,
                        "supporting_passage": item.supporting_passage,
                        "is_verified": is_verified,
                    }
                )

        return saved_records

    def get_evidence_table(self, work_id: str | None = None) -> list[dict[str, Any]]:
        """Retrieve stored evidence records with work metadata."""
        query = """
            SELECT e.evidence_id, e.work_id, w.title, w.doi, w.zotero_key,
                   e.claim_type, e.content, e.page_start, e.page_end,
                   e.supporting_passage, e.is_verified, e.created_at
            FROM evidence_records e
            JOIN works w ON e.work_id = w.work_id
        """
        params = []
        if work_id:
            query += " WHERE e.work_id = ?"
            params.append(work_id)
        query += " ORDER BY e.created_at DESC"

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]
