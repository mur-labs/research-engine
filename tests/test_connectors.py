"""Unit tests for Academic API connectors (OpenAlex, Crossref, Semantic Scholar)."""

import json
from pathlib import Path
import pytest
import respx
import httpx

from research_engine.connectors.openalex import OpenAlexConnector
from research_engine.connectors.crossref import CrossrefConnector
from research_engine.connectors.semanticscholar import SemanticScholarConnector
from research_engine.models import RetrievalStatus


# --- OpenAlex Tests ---

@respx.mock
def test_openalex_search_success():
    connector = OpenAlexConnector(base_url="https://api.openalex.org", email="test@example.com")

    mock_payload = {
        "meta": {"count": 1, "next_cursor": "cursor_next_token"},
        "results": [
            {
                "id": "https://openalex.org/W123456789",
                "doi": "https://doi.org/10.1017/s0003055420000123",
                "title": "Affective Polarization and Democratic Erosion",
                "publication_year": 2021,
                "publication_date": "2021-04-15",
                "cited_by_count": 85,
                "authorships": [
                    {
                        "author": {"display_name": "Jane Doe", "orcid": "https://orcid.org/0000-0002-1825-0097"},
                        "institutions": [{"display_name": "Harvard University"}]
                    }
                ],
                "primary_location": {
                    "source": {"display_name": "American Political Science Review", "host_organization_name": "Cambridge University Press"},
                    "landing_page_url": "https://doi.org/10.1017/s0003055420000123"
                },
                "open_access": {
                    "is_oa": True,
                    "oa_url": "https://cambridge.org/core/services/aop-cambridge-core/content/view/sample.pdf"
                },
                "abstract_inverted_index": {
                    "Democratic": [0],
                    "erosion": [1],
                    "is": [2],
                    "linked": [3],
                    "to": [4],
                    "polarization.": [5]
                },
                "biblio": {"volume": "115", "issue": "2", "first_page": "450", "last_page": "468"}
            }
        ]
    }

    respx.get("https://api.openalex.org/works").respond(status_code=200, json=mock_payload)

    result = connector.search(query="affective polarization", limit=10)

    assert result.total_found == 1
    assert result.has_more is True
    assert result.next_page_cursor == "cursor_next_token"
    assert len(result.works) == 1

    work = result.works[0]
    assert work.doi == "10.1017/s0003055420000123"
    assert work.title == "Affective Polarization and Democratic Erosion"
    assert work.publication_year == 2021
    assert work.venue == "American Political Science Review"
    assert len(work.authors) == 1
    assert work.authors[0].name == "Jane Doe"
    assert work.authors[0].affiliation == "Harvard University"
    assert work.is_oa is True
    assert work.oa_url.endswith("sample.pdf")
    assert work.abstract == "Democratic erosion is linked to polarization."
    assert work.pages == "450-468"
    assert work.retrieval_status == RetrievalStatus.OA_LOCATION_FOUND


@respx.mock
def test_openalex_get_by_doi():
    connector = OpenAlexConnector(base_url="https://api.openalex.org")
    doi = "10.1017/s0003055420000123"

    mock_work = {
        "id": "https://openalex.org/W123",
        "doi": f"https://doi.org/{doi}",
        "title": "Exact Title",
        "publication_year": 2020,
    }
    respx.get(f"https://api.openalex.org/works/https://doi.org/{doi}").respond(status_code=200, json=mock_work)

    work = connector.get_by_doi(doi)
    assert work is not None
    assert work.doi == doi
    assert work.title == "Exact Title"


# --- Crossref Tests ---

@respx.mock
def test_crossref_search_success():
    connector = CrossrefConnector(base_url="https://api.crossref.org")

    mock_payload = {
        "message": {
            "total-results": 1,
            "next-cursor": "cr_cursor_123",
            "items": [
                {
                    "DOI": "10.1111/ajps.12567",
                    "title": ["Partisan Animus and Institutional Trust"],
                    "author": [
                        {"given": "Alex", "family": "Smith", "affiliation": [{"name": "Oxford University"}]}
                    ],
                    "published": {"date-parts": [[2022, 5, 20]]},
                    "container-title": ["American Journal of Political Science"],
                    "publisher": "Wiley",
                    "volume": "66",
                    "issue": "3",
                    "page": "600-615",
                    "is-referenced-by-count": 42,
                    "abstract": "<jats:p>We examine partisan hostility.</jats:p>",
                    "URL": "http://dx.doi.org/10.1111/ajps.12567"
                }
            ]
        }
    }

    respx.get("https://api.crossref.org/works").respond(status_code=200, json=mock_payload)

    result = connector.search("partisan hostility", limit=5)
    assert result.total_found == 1
    assert len(result.works) == 1

    work = result.works[0]
    assert work.doi == "10.1111/ajps.12567"
    assert work.title == "Partisan Animus and Institutional Trust"
    assert work.publication_year == 2022
    assert work.publication_date == "2022-05-20"
    assert work.authors[0].name == "Alex Smith"
    assert work.citation_count == 42
    assert work.abstract == "We examine partisan hostility."
    assert work.venue == "American Journal of Political Science"


# --- Semantic Scholar Tests ---

@respx.mock
def test_semanticscholar_search_success():
    connector = SemanticScholarConnector(base_url="https://api.semanticscholar.org/graph/v1")

    mock_payload = {
        "total": 1,
        "next": 10,
        "data": [
            {
                "paperId": "abcdef1234567890",
                "title": "Partisan Sorting in Comparative Perspective",
                "year": 2023,
                "publicationDate": "2023-01-10",
                "authors": [{"name": "Carlos Gomez"}],
                "venue": "Comparative Political Studies",
                "citationCount": 15,
                "isOpenAccess": True,
                "openAccessPdf": {"url": "https://example.org/open.pdf"},
                "externalIds": {"DOI": "10.1177/0010414022114", "CorpusId": 998877}
            }
        ]
    }

    respx.get("https://api.semanticscholar.org/graph/v1/paper/search").respond(status_code=200, json=mock_payload)

    result = connector.search("partisan sorting", limit=10)
    assert result.total_found == 1
    assert len(result.works) == 1

    work = result.works[0]
    assert work.doi == "10.1177/0010414022114"
    assert work.title == "Partisan Sorting in Comparative Perspective"
    assert work.source_identifiers["semanticscholar"] == "abcdef1234567890"
    assert work.source_identifiers["corpus_id"] == "998877"
    assert work.is_oa is True
    assert work.oa_url == "https://example.org/open.pdf"


def test_crossref_fallback_work_id_avoids_title_collision():
    connector = CrossrefConnector(base_url="https://api.crossref.org")
    w1 = connector._normalize_work({
        "title": ["Editorial"],
        "author": [{"given": "Alice", "family": "Smith"}],
        "published": {"date-parts": [[2021]]},
    })
    w2 = connector._normalize_work({
        "title": ["Editorial"],
        "author": [{"given": "Bob", "family": "Jones"}],
        "published": {"date-parts": [[2023]]},
    })
    assert w1.work_id != w2.work_id


@respx.mock
def test_semanticscholar_forwards_supported_filters():
    connector = SemanticScholarConnector(base_url="https://api.semanticscholar.org/graph/v1")
    route = respx.get("https://api.semanticscholar.org/graph/v1/paper/search").respond(
        status_code=200,
        json={"total": 0, "data": []},
    )

    connector.search("polarization", limit=10, filters={"year": "2020-2024"})
    assert route.called
    assert route.calls[0].request.url.params["year"] == "2020-2024"


@respx.mock
def test_connector_does_not_retry_404():
    connector = OpenAlexConnector(base_url="https://api.openalex.org")
    route = respx.get("https://api.openalex.org/works/https://doi.org/10.9999/missing").respond(status_code=404)

    assert connector.get_by_doi("10.9999/missing") is None
    assert route.call_count == 1
