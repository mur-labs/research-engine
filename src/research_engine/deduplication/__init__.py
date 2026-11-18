"""Deduplication package init."""

from research_engine.deduplication.engine import DeduplicationEngine, normalize_title, normalize_author_family

__all__ = ["DeduplicationEngine", "normalize_title", "normalize_author_family"]
