"""Crossref Academic API Connector."""

import hashlib
from typing import Any
from research_engine.connectors.base import BaseAcademicConnector, ConnectorResult
from research_engine.models import Author, Work, RetrievalStatus


class CrossrefConnector(BaseAcademicConnector):
    """Connector for Crossref REST API."""

    name = "crossref"

    def _normalize_work(self, item: dict[str, Any]) -> Work:
        doi = self._clean_doi(item.get("DOI"))
        
        # Crossref titles are usually lists
        raw_titles = item.get("title", [])
        title = raw_titles[0] if raw_titles else "Untitled Document"

        authors: list[Author] = []
        for a in item.get("author", []):
            given = a.get("given", "")
            family = a.get("family", "")
            name = f"{given} {family}".strip() if given or family else a.get("name", "")
            if name:
                orcid = a.get("ORCID")
                affils = a.get("affiliation", [])
                affil_name = affils[0].get("name") if affils else None
                authors.append(Author(name=name, orcid=orcid, affiliation=affil_name))

        # Year from published-print or published-online
        pub_year = None
        date_parts = None
        for date_field in ["published", "published-print", "published-online", "issued"]:
            if date_field in item and "date-parts" in item[date_field]:
                parts = item[date_field]["date-parts"]
                if parts and parts[0]:
                    date_parts = parts[0]
                    pub_year = date_parts[0]
                    break

        if doi:
            work_id = f"doi_{hashlib.sha256(doi.encode('utf-8')).hexdigest()[:16]}"
        else:
            first_author = authors[0].name if authors else ""
            fallback_seed = f"{title}|{first_author}|{pub_year or ''}"
            work_id = f"cr_{hashlib.sha256(fallback_seed.encode('utf-8')).hexdigest()[:16]}"

        pub_date_str = None
        if date_parts:
            pub_date_str = "-".join(f"{p:02d}" if idx > 0 else f"{p}" for idx, p in enumerate(date_parts))

        # Containers & Publisher
        containers = item.get("container-title", [])
        venue = containers[0] if containers else None
        publisher = item.get("publisher")

        volume = item.get("volume")
        issue = item.get("issue")
        page = item.get("page")

        # Abstract
        abstract = item.get("abstract")
        if abstract and abstract.startswith("<jats:p>"):
            # Strip simple JATS tags if present
            import re
            abstract = re.sub(r"<[^>]+>", "", abstract).strip()

        # Link for landing page / OA
        landing_page = item.get("URL")
        oa_url = None
        is_oa = False
        for link in item.get("link", []):
            if link.get("content-type") == "application/pdf":
                oa_url = link.get("URL")
                is_oa = True
                break

        retrieval_status = RetrievalStatus.OA_LOCATION_FOUND if is_oa and oa_url else (
            RetrievalStatus.ABSTRACT_AVAILABLE if abstract else RetrievalStatus.METADATA_ONLY
        )

        return Work(
            work_id=work_id,
            doi=doi,
            title=title,
            authors=authors,
            publication_year=pub_year,
            publication_date=pub_date_str,
            venue=venue,
            publisher=publisher,
            volume=volume,
            issue=issue,
            pages=page,
            abstract=abstract,
            citation_count=item.get("is-referenced-by-count", 0),
            is_oa=is_oa,
            oa_url=oa_url,
            landing_page_url=landing_page,
            source_identifiers={"crossref": doi} if doi else {},
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
        """Search Crossref works."""
        params: dict[str, Any] = {
            "query": query,
            "rows": min(limit, 100),
        }

        if cursor_or_page is not None:
            if isinstance(cursor_or_page, int):
                params["offset"] = (cursor_or_page - 1) * limit
            else:
                params["cursor"] = cursor_or_page
        else:
            params["cursor"] = "*"

        if filters:
            filter_parts = [f"{k}:{v}" for k, v in filters.items()]
            params["filter"] = ",".join(filter_parts)

        resp = self._execute_http_get("works", params=params)
        data = resp.json()

        message = data.get("message", {})
        items = message.get("items", [])
        works = [self._normalize_work(item) for item in items]

        total_results = message.get("total-results", len(works))
        next_cursor = message.get("next-cursor")

        return ConnectorResult(
            works=works,
            total_found=total_results,
            raw_payload=data,
            has_more=bool(next_cursor and items),
            next_page_cursor=next_cursor,
        )

    def get_by_doi(self, doi: str) -> Work | None:
        """Fetch exact bibliographic record by DOI."""
        clean = self._clean_doi(doi)
        if not clean:
            return None
        try:
            resp = self._execute_http_get(f"works/{clean}")
            data = resp.json()
            return self._normalize_work(data.get("message", {}))
        except Exception:
            return None
