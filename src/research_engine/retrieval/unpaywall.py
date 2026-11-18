"""Unpaywall Open Access Resolver."""

from typing import Any
import httpx
from pydantic import BaseModel
from research_engine.config import ApiServiceConfig
from research_engine.connectors.base import clean_doi


class OAResolveResult(BaseModel):
    doi: str
    is_oa: bool = False
    oa_url: str | None = None
    oa_status: str | None = None  # gold, green, bronze, hybrid, closed
    license: str | None = None
    version: str | None = None  # publishedVersion, acceptedVersion, submittedVersion


class UnpaywallResolver:
    """Queries Unpaywall REST API to locate legitimate Open Access versions of scholarly works."""

    def __init__(self, config: ApiServiceConfig):
        self.base_url = config.base_url.rstrip("/")
        self.email = config.email or "researcher@example.com"

    def resolve_doi(self, doi: str) -> OAResolveResult:
        """Query Unpaywall for OA availability for a given DOI."""
        clean = clean_doi(doi)
        if not clean:
            return OAResolveResult(doi="", is_oa=False)

        url = f"{self.base_url}/{clean}"
        params = {"email": self.email}

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(url, params=params)
                if resp.status_code == 404:
                    return OAResolveResult(doi=clean, is_oa=False)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return OAResolveResult(doi=clean, is_oa=False)

        is_oa = bool(data.get("is_oa", False))
        best_oa = data.get("best_oa_location") or {}
        oa_url = best_oa.get("url_for_pdf") or best_oa.get("url")

        return OAResolveResult(
            doi=clean,
            is_oa=is_oa,
            oa_url=oa_url,
            oa_status=data.get("oa_status"),
            license=best_oa.get("license"),
            version=best_oa.get("version"),
        )
