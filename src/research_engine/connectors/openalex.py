"""OpenAlex Academic API Connector."""

import hashlib
from typing import Any
from research_engine.connectors.base import BaseAcademicConnector, ConnectorResult
from research_engine.models import Author, Work, RetrievalStatus


class OpenAlexConnector(BaseAcademicConnector):
    """Connector for OpenAlex REST API."""

    name = "openalex"

    def _normalize_work(self, item: dict[str, Any]) -> Work:
        doi = self._clean_doi(item.get("doi"))
        title = item.get("title") or "Untitled Document"

        authors: list[Author] = []
        for authorship in item.get("authorships", []):
            author_dict = authorship.get("author", {})
            raw_name = author_dict.get("display_name")
            if raw_name:
                orcid = author_dict.get("orcid")
                institutions = authorship.get("institutions", [])
                affil = institutions[0].get("display_name") if institutions else None
                authors.append(Author(name=raw_name, orcid=orcid, affiliation=affil))

        # Unique work ID deterministic from DOI, OpenAlex ID, or title+author+year
        openalex_id = item.get("id", "")
        clean_oa_id = openalex_id.split("/")[-1] if openalex_id else ""
        if doi:
            work_id = f"doi_{hashlib.sha256(doi.encode('utf-8')).hexdigest()[:16]}"
        elif clean_oa_id:
            work_id = f"oa_{clean_oa_id}"
        else:
            first_author = authors[0].name if authors else ""
            fallback_seed = f"{title}|{first_author}|{item.get('publication_year') or ''}"
            work_id = f"gen_{hashlib.sha256(fallback_seed.encode('utf-8')).hexdigest()[:16]}"

        # Venue / Primary location
        primary_loc = item.get("primary_location") or {}
        source_dict = primary_loc.get("source") or {}
        venue = source_dict.get("display_name")
        publisher = source_dict.get("host_organization_name")
        landing_page = primary_loc.get("landing_page_url")

        # Open Access
        oa_dict = item.get("open_access") or {}
        is_oa = bool(oa_dict.get("is_oa", False))
        oa_url = oa_dict.get("oa_url")

        # Inverted index abstract to text if available
        abstract = None
        inv_abstract = item.get("abstract_inverted_index")
        if isinstance(inv_abstract, dict):
            words: list[tuple[int, str]] = []
            for word, positions in inv_abstract.items():
                for pos in positions:
                    words.append((pos, word))
            words.sort(key=lambda x: x[0])
            abstract = " ".join(w[1] for w in words)

        # Biblio details
        biblio = item.get("biblio") or {}
        volume = biblio.get("volume")
        issue = biblio.get("issue")
        first_page = biblio.get("first_page")
        last_page = biblio.get("last_page")
        pages = f"{first_page}-{last_page}" if first_page and last_page else first_page

        retrieval_status = RetrievalStatus.OA_LOCATION_FOUND if is_oa and oa_url else (
            RetrievalStatus.ABSTRACT_AVAILABLE if abstract else RetrievalStatus.METADATA_ONLY
        )

        return Work(
            work_id=work_id,
            doi=doi,
            title=title,
            authors=authors,
            publication_year=item.get("publication_year"),
            publication_date=item.get("publication_date"),
            venue=venue,
            publisher=publisher,
            volume=volume,
            issue=issue,
            pages=pages,
            abstract=abstract,
            citation_count=item.get("cited_by_count", 0),
            is_oa=is_oa,
            oa_url=oa_url,
            landing_page_url=landing_page,
            source_identifiers={"openalex": clean_oa_id} if clean_oa_id else {},
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
        """Search OpenAlex works."""
        params: dict[str, Any] = {
            "search": query,
            "per_page": min(limit, 100),
        }

        # Cursor-based or standard pagination
        if cursor_or_page is not None:
            if isinstance(cursor_or_page, int):
                params["page"] = cursor_or_page
            else:
                params["cursor"] = cursor_or_page
        else:
            params["cursor"] = "*"

        # Additional filter criteria if supplied
        if filters:
            filter_parts: list[str] = []
            for k, v in filters.items():
                filter_parts.append(f"{k}:{v}")
            params["filter"] = ",".join(filter_parts)

        resp = self._execute_http_get("works", params=params)
        data = resp.json()

        results_list = data.get("results", [])
        works = [self._normalize_work(item) for item in results_list]

        meta = data.get("meta", {})
        total_found = meta.get("count", len(works))
        next_cursor = meta.get("next_cursor")

        return ConnectorResult(
            works=works,
            total_found=total_found,
            raw_payload=data,
            has_more=bool(next_cursor),
            next_page_cursor=next_cursor,
        )

    def get_by_doi(self, doi: str) -> Work | None:
        """Resolve a specific DOI in OpenAlex."""
        clean = self._clean_doi(doi)
        if not clean:
            return None
        try:
            resp = self._execute_http_get(f"works/https://doi.org/{clean}")
            return self._normalize_work(resp.json())
        except Exception:
            return None
