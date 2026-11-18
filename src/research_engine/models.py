"""Domain models and Pydantic schemas for the Research Engine."""

from datetime import datetime
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class PlanStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ReviewMode(str, Enum):
    EXPLORATORY = "exploratory"
    SYSTEMATIC = "systematic"


class RetrievalStatus(str, Enum):
    METADATA_ONLY = "metadata_only"
    ABSTRACT_AVAILABLE = "abstract_available"
    OA_LOCATION_FOUND = "oa_location_found"
    AWAITING_MANUAL_RETRIEVAL = "awaiting_manual_retrieval"
    FULL_TEXT_AVAILABLE = "full_text_available"
    EXTRACTION_COMPLETE = "extraction_complete"
    EXTRACTION_FAILED = "extraction_failed"
    ACCESS_UNAVAILABLE = "access_unavailable"
    EXCLUDED = "excluded"


class ScreeningDecision(str, Enum):
    UNSCREENED = "unscreened"
    INCLUDED = "included"
    EXCLUDED = "excluded"
    UNCERTAIN = "uncertain"


class EvidenceType(str, Enum):
    DIRECT_QUOTATION = "direct_quotation"
    FAITHFUL_PARAPHRASE = "faithful_paraphrase"
    AUTHOR_CONCLUSION = "author_conclusion"
    ENGINE_INTERPRETATION = "engine_interpretation"
    AI_HYPOTHESIS = "ai_hypothesis"


# --- Search Planning Models ---

class SearchQueryPlan(BaseModel):
    query_id: str
    target_database: str  # e.g., 'openalex', 'crossref', 'semanticscholar'
    query_string: str
    purpose: str
    query_type: str = "broad"  # broad, focused, supplementary
    filters: dict[str, Any] = Field(default_factory=dict)
    is_approved: bool = False


class ConceptMap(BaseModel):
    core_concepts: list[str] = Field(default_factory=list)
    synonyms: dict[str, list[str]] = Field(default_factory=dict)
    related_concepts: list[str] = Field(default_factory=list)
    competing_explanations: list[str] = Field(default_factory=list)


class SearchPlan(BaseModel):
    plan_id: str
    version: int = 1
    research_question: str
    theoretical_framework: str | None = None
    discipline_scope: str | None = None
    review_mode: ReviewMode = ReviewMode.EXPLORATORY
    concept_map: ConceptMap = Field(default_factory=ConceptMap)
    queries: list[SearchQueryPlan] = Field(default_factory=list)
    inclusion_criteria: list[str] = Field(default_factory=list)
    exclusion_criteria: list[str] = Field(default_factory=list)
    status: PlanStatus = PlanStatus.DRAFT
    created_at: datetime = Field(default_factory=datetime.utcnow)
    approved_at: datetime | None = None


# --- Scholarly Works & Provenance Models ---

class Author(BaseModel):
    name: str
    orcid: str | None = None
    affiliation: str | None = None


class Work(BaseModel):
    work_id: str  # Deterministic UUID or hash
    doi: str | None = None
    title: str
    authors: list[Author] = Field(default_factory=list)
    publication_year: int | None = None
    publication_date: str | None = None
    venue: str | None = None  # Journal or conference name
    publisher: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    abstract: str | None = None
    citation_count: int | None = None
    is_oa: bool = False
    oa_url: str | None = None
    landing_page_url: str | None = None
    source_identifiers: dict[str, str] = Field(default_factory=dict)  # {'openalex': '...', 's2': '...'}
    zotero_key: str | None = None
    screening_decision: ScreeningDecision = ScreeningDecision.UNSCREENED
    retrieval_status: RetrievalStatus = RetrievalStatus.METADATA_ONLY
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class SearchRun(BaseModel):
    run_id: str
    plan_id: str
    plan_version: int
    executed_at: datetime = Field(default_factory=datetime.utcnow)
    target_database: str
    query_string: str
    total_results_found: int = 0
    records_retrieved: int = 0
    new_records_added: int = 0
    error_message: str | None = None
