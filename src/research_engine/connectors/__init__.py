"""Academic API Connectors package."""

from research_engine.connectors.base import BaseAcademicConnector, ConnectorResult
from research_engine.connectors.openalex import OpenAlexConnector
from research_engine.connectors.crossref import CrossrefConnector
from research_engine.connectors.semanticscholar import SemanticScholarConnector

__all__ = [
    "BaseAcademicConnector",
    "ConnectorResult",
    "OpenAlexConnector",
    "CrossrefConnector",
    "SemanticScholarConnector",
]
