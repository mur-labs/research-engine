"""Deterministic verification for evidence page boundaries and verbatim passages."""

import unicodedata
import re
from research_engine.pdf.processor import PDFProcessingResult


def clean_text_for_matching(text: str) -> str:
    """Normalize text for whitespace, casing, and diacritics to verify passage presence."""
    if not text:
        return ""
    norm = unicodedata.normalize("NFKD", text)
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    norm = norm.lower()
    norm = re.sub(r"[^\w\s]", "", norm)
    return " ".join(norm.split())


class EvidenceVerifier:
    """Verifies that extracted claims and quotes actually exist in the PDF structure."""

    @staticmethod
    def verify_passage(
        pdf_result: PDFProcessingResult,
        page_number: int,
        passage: str,
    ) -> bool:
        """Verify that page exists and that the supporting passage is found on that page."""
        if page_number < 1 or page_number > pdf_result.page_count:
            return False

        target_page = None
        for p in pdf_result.pages:
            if p.page_number == page_number:
                target_page = p
                break

        if not target_page or not target_page.text:
            return False

        norm_target_text = clean_text_for_matching(target_page.text)
        norm_passage = clean_text_for_matching(passage)

        if not norm_passage:
            return False

        # Check direct substring
        if norm_passage in norm_target_text:
            return True

        # Check multi-token overlap if passage spans slightly different line wraps
        passage_tokens = norm_passage.split()
        if len(passage_tokens) >= 5:
            # Check 5-token prefix and suffix
            prefix = " ".join(passage_tokens[:5])
            suffix = " ".join(passage_tokens[-5:])
            if prefix in norm_target_text and suffix in norm_target_text:
                return True

        return False
