"""Abstract base class and normalized response types for Academic API connectors."""

import abc
import time
from typing import Any
import httpx
from pydantic import BaseModel, Field

from research_engine.models import Work, Author


def clean_doi(doi_raw: str | None) -> str | None:
    """Normalize a DOI string by stripping common URL/prefix wrappers and trailing slashes."""
    if not doi_raw:
        return None
    doi = doi_raw.strip().lower()
    for prefix in ["https://doi.org/", "http://doi.org/", "doi.org/", "doi:"]:
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
    return doi.strip("/") or None


class ConnectorResult(BaseModel):
    """Normalized output from any academic API search request."""
    works: list[Work] = Field(default_factory=list)
    total_found: int = 0
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    has_more: bool = False
    next_page_cursor: str | None = None


class BaseAcademicConnector(abc.ABC):
    """Base interface for all academic database connectors."""

    name: str
    _clean_doi = staticmethod(clean_doi)

    def __init__(
        self,
        base_url: str,
        email: str = "",
        api_key: str = "",
        rate_limit_per_second: float = 5.0,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.api_key = api_key
        self.rate_limit_per_second = rate_limit_per_second
        self.timeout = timeout
        self._min_interval = 1.0 / rate_limit_per_second if rate_limit_per_second > 0 else 0.0
        self._last_call_time = 0.0

    def _apply_rate_limit(self) -> None:
        """Throttle calls to respect polite pool or provider rate limits."""
        elapsed = time.time() - self._last_call_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call_time = time.time()

    def _get_headers(self) -> dict[str, str]:
        """Construct polite User-Agent and authentication headers."""
        headers = {
            "User-Agent": f"ResearchEngine/0.1.0 (mailto:{self.email or 'researcher@local.lan'})"
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    def _execute_http_get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        max_retries: int = 3,
    ) -> httpx.Response:
        """Execute HTTP GET with rate limiting, retries, and exponential backoff."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = self._get_headers()
        backoff = 1.0

        for attempt in range(max_retries):
            self._apply_rate_limit()
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.get(url, params=params, headers=headers)
                    if resp.status_code == 429:
                        time.sleep(backoff)
                        backoff *= 2.0
                        continue
                    resp.raise_for_status()
                    return resp
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500 or attempt == max_retries - 1:
                    raise exc
                time.sleep(backoff)
                backoff *= 2.0
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                if attempt == max_retries - 1:
                    raise exc
                time.sleep(backoff)
                backoff *= 2.0

        raise RuntimeError(f"Failed to query {url} after {max_retries} attempts.")

    @abc.abstractmethod
    def search(
        self,
        query: str,
        limit: int = 25,
        cursor_or_page: str | int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> ConnectorResult:
        """Execute search query and return normalized results."""
        pass

    @abc.abstractmethod
    def get_by_doi(self, doi: str) -> Work | None:
        """Fetch single work record by DOI."""
        pass
