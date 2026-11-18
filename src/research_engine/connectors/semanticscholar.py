"""Semantic Scholar Academic API Connector."""

import hashlib
import logging
from typing import Any
from research_engine.connectors.base import BaseAcademicConnector, ConnectorResult
from research_engine.models import Author, Work, RetrievalStatus

logger = logging.getLogger(__name__)
_S2_SUPPORTED_FILTERS = {"year", "publicationTypes", "fieldsOfStudy", "venue", "openAccessPdf"}


class SemanticScholarConnector(BaseAcademicConnector):
    """Connector for Semantic Scholar Graph API."""

    name = "semanticscholar"

    def _normalize_work(self, item: dict[str, Any]) -> Work:
        external_ids = item.get("externalIds") or {}
        doi = self._clean_doi(external_ids.get("DOI"))
        s2_id = item.get("paperId", "")
        title = item.get("title") or "Untitled Document"

        authors: list[Author] = []
        for a in item.get("authors", []):
            name = a.get("name")
            if name:
                authors.append(Author(name=name))

        if doi:
            work_id = f"doi_{hashlib.sha256(doi.encode('utf-8')).hexdigest()[:16]}"
        elif s2_id:
            work_id = f"s2_{s2_id[:16]}"
        else:
            first_author = authors[0].name if authors else ""
            fallback_seed = f"{title}|{first_author}|{item.get('year') or ''}"
            work_id = f"gen_{hashlib.sha256(fallback_seed.encode('utf-8')).hexdigest()[:16]}"

        # Venue / Publication
        venue = item.get("venue")
        pub_venue = item.get("publicationVenue") or {}
        if not venue and pub_venue:
            venue = pub_venue.get("name")

        # OA link & Open Access status
        open_access_pdf = item.get("openAccessPdf") or {}
        oa_url = open_access_pdf.get("url")
        is_oa = item.get("isOpenAccess", False) or bool(oa_url)

        abstract = item.get("abstract")

        retrieval_status = RetrievalStatus.OA_LOCATION_FOUND if is_oa and oa_url else (
            RetrievalStatus.ABSTRACT_AVAILABLE if abstract else RetrievalStatus.METADATA_ONLY
        )

        source_ids = {}
        if s2_id:
            source_ids["semanticscholar"] = s2_id
        if external_ids.get("CorpusId"):
            source_ids["corpus_id"] = str(external_ids["CorpusId"])

        return Work(
            work_id=work_id,
            doi=doi,
            title=title,
            authors=authors,
            publication_year=item.get("year"),
            publication_date=item.get("publicationDate"),
            venue=venue,
            abstract=abstract,
            citation_count=item.get("citationCount", 0),
            is_oa=is_oa,
            oa_url=oa_url,
            landing_page_url=item.get("url"),
            source_identifiers=source_ids,
            retrieval_status=retrieval_status,
            raw_metadata=item,
        )

    def search(
        self,
        query: str,
        limit: int = 25,
        cursor_or_page: str | int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> ConnectorResult:
        """Search Semantic Scholar papers."""
        fields = "paperId,title,abstract,authors,year,publicationDate,venue,publicationVenue,isOpenAccess,openAccessPdf,citationCount,url,externalIds"
        offset = 0
        if isinstance(cursor_or_page, int):
            offset = (cursor_or_page - 1) * limit

        params: dict[str, Any] = {
            "query": query,
            "limit": min(limit, 100),
            "offset": offset,
            "fields": fields,
        }
        if filters:
            for k, v in filters.items():
                if k in _S2_SUPPORTED_FILTERS:
                    params[k] = v
                else:
                    logger.warning("Semantic Scholar connector ignoring unsupported filter: %s", k)

        resp = self._execute_http_get("paper/search", params=params)
        data = resp.json()

        items = data.get("data", [])
        works = [self._normalize_work(item) for item in items]
        total = data.get("total", len(works))
        next_offset = data.get("next")

        return ConnectorResult(
            works=works,
            total_found=total,
            raw_payload=data,
            has_more=bool(next_offset),
            next_page_cursor=str(next_offset) if next_offset is not None else None,
        )

    def get_by_doi(self, doi: str) -> Work | None:
        """Fetch paper metadata from Semantic Scholar by DOI."""
        clean = self._clean_doi(doi)
        if not clean:
            return None
        fields = "paperId,title,abstract,authors,year,publicationDate,venue,publicationVenue,isOpenAccess,openAccessPdf,citationCount,url,externalIds"
        try:
            resp = self._execute_http_get(f"paper/DOI:{clean}", params={"fields": fields})
            return self._normalize_work(resp.json())
        except Exception:
            return None
