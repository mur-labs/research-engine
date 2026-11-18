"""Deduplication engine with strict precedence: DOI -> Stable IDs -> Title/Author/Year."""

import re
import unicodedata
from typing import Any
from research_engine.database import DatabaseManager
from research_engine.models import Work, Author, RetrievalStatus


def normalize_title(title: str | None) -> str:
    """Normalize title by replacing ampersands, removing punctuation, extra whitespace, and diacritics."""
    if not title:
        return ""
    # Replace ampersands with 'and'
    title = title.replace("&", " and ")
    # NFKD decomposition to remove accents
    norm = unicodedata.normalize("NFKD", title)
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    # Lowercase and remove punctuation
    norm = norm.lower()
    norm = re.sub(r"[^\w\s]", "", norm)
    # Collapse whitespace
    return " ".join(norm.split())


def normalize_author_family(name: str | None) -> str:
    """Extract and normalize the likely family name or primary token of an author."""
    if not name:
        return ""
    tokens = [t.lower() for t in re.sub(r"[^\w\s]", "", name).split()]
    return tokens[-1] if tokens else ""


class DeduplicationEngine:
    """Identifies duplicate candidate works and merges metadata without destructive loss."""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def find_existing_work(self, candidate: Work) -> Work | None:
        """Find matching work in database using strict precedence rules."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # Precedence 1: Normalized DOI
            if candidate.doi:
                cursor.execute(
                    "SELECT work_id FROM works WHERE LOWER(doi) = LOWER(?)",
                    (candidate.doi,),
                )
                row = cursor.fetchone()
                if row:
                    return self._load_work_by_id(row["work_id"])

            # Precedence 2: Stable Source-specific Identifiers
            for id_type, id_val in candidate.source_identifiers.items():
                cursor.execute(
                    """
                    SELECT work_id FROM work_identifiers
                    WHERE identifier_type = ? AND identifier_value = ?
                    """,
                    (id_type, id_val),
                )
                row = cursor.fetchone()
                if row:
                    return self._load_work_by_id(row["work_id"])

            # Precedence 3: Title + First Author Family Name + Year matching
            norm_candidate_title = normalize_title(candidate.title)
            candidate_family = (
                normalize_author_family(candidate.authors[0].name)
                if candidate.authors
                else ""
            )

            if norm_candidate_title and len(norm_candidate_title) > 15:
                # Retrieve candidate works with the same publication year (+/- 1 year margin)
                year_clause = ""
                params: list[Any] = []
                if candidate.publication_year:
                    year_clause = "WHERE publication_year BETWEEN ? AND ?"
                    params = [candidate.publication_year - 1, candidate.publication_year + 1]

                cursor.execute(f"SELECT work_id, title, publication_year FROM works {year_clause}", params)
                rows = cursor.fetchall()

                for row in rows:
                    if normalize_title(row["title"]) == norm_candidate_title:
                        # Also check author if candidate has author info
                        if candidate_family:
                            existing_work = self._load_work_by_id(row["work_id"])
                            if existing_work and existing_work.authors:
                                existing_family = normalize_author_family(existing_work.authors[0].name)
                                if existing_family == candidate_family:
                                    return existing_work
                        else:
                            return self._load_work_by_id(row["work_id"])

        return None

    def _load_work_by_id(self, work_id: str) -> Work | None:
        """Helper to reconstruct a Work model from database records."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM works WHERE work_id = ?", (work_id,))
            w_row = cursor.fetchone()
            if not w_row:
                return None

            # Authors
            cursor.execute(
                """
                SELECT a.name, a.orcid, a.affiliation
                FROM authors a
                JOIN authorships ash ON a.author_id = ash.author_id
                WHERE ash.work_id = ?
                ORDER BY ash.author_position ASC
                """,
                (work_id,),
            )
            authors = [
                Author(name=r["name"], orcid=r["orcid"], affiliation=r["affiliation"])
                for r in cursor.fetchall()
            ]

            # Identifiers
            cursor.execute(
                "SELECT identifier_type, identifier_value FROM work_identifiers WHERE work_id = ?",
                (work_id,),
            )
            source_ids = {r["identifier_type"]: r["identifier_value"] for r in cursor.fetchall()}

        return Work(
            work_id=w_row["work_id"],
            doi=w_row["doi"],
            title=w_row["title"],
            authors=authors,
            publication_year=w_row["publication_year"],
            publication_date=w_row["publication_date"],
            venue=w_row["venue"],
            publisher=w_row["publisher"],
            volume=w_row["volume"],
            issue=w_row["issue"],
            pages=w_row["pages"],
            abstract=w_row["abstract"],
            citation_count=w_row["citation_count"],
            is_oa=bool(w_row["is_oa"]),
            oa_url=w_row["oa_url"],
            landing_page_url=w_row["landing_page_url"],
            source_identifiers=source_ids,
            zotero_key=w_row["zotero_key"],
            screening_decision=w_row["screening_decision"],
            retrieval_status=w_row["retrieval_status"],
        )

    def merge_or_insert_work(self, candidate: Work) -> tuple[Work, bool]:
        """Insert candidate or non-destructively enrich existing work. Returns (work, is_new)."""
        existing = self.find_existing_work(candidate)

        if not existing:
            # New record
            self._insert_work(candidate)
            return candidate, True

        # Enrich existing record non-destructively
        updated_doi = existing.doi or candidate.doi
        updated_abstract = existing.abstract or candidate.abstract
        updated_venue = existing.venue or candidate.venue
        updated_publisher = existing.publisher or candidate.publisher
        updated_oa_url = existing.oa_url or candidate.oa_url
        updated_is_oa = existing.is_oa or candidate.is_oa
        updated_citations = max(existing.citation_count or 0, candidate.citation_count or 0)

        updated_retrieval_status = existing.retrieval_status
        if (
            updated_is_oa
            and updated_oa_url
            and existing.retrieval_status in (RetrievalStatus.METADATA_ONLY, RetrievalStatus.ABSTRACT_AVAILABLE)
        ):
            updated_retrieval_status = RetrievalStatus.OA_LOCATION_FOUND

        # Merge identifiers
        merged_ids = dict(existing.source_identifiers)
        merged_ids.update(candidate.source_identifiers)

        with self.db.get_connection() as conn:
            conn.execute(
                """
                UPDATE works
                SET doi = ?, abstract = ?, venue = ?, publisher = ?,
                    oa_url = ?, is_oa = ?, citation_count = ?, retrieval_status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE work_id = ?
                """,
                (
                    updated_doi,
                    updated_abstract,
                    updated_venue,
                    updated_publisher,
                    updated_oa_url,
                    1 if updated_is_oa else 0,
                    updated_citations,
                    updated_retrieval_status.value,
                    existing.work_id,
                ),
            )
            # Add any new source identifiers
            for id_type, id_val in candidate.source_identifiers.items():
                conn.execute(
                    """
                    INSERT OR IGNORE INTO work_identifiers (work_id, identifier_type, identifier_value)
                    VALUES (?, ?, ?)
                    """,
                    (existing.work_id, id_type, id_val),
                )

        refreshed = self._load_work_by_id(existing.work_id)
        return refreshed or existing, False

    def _insert_work(self, work: Work) -> None:
        """Insert a brand new work into works, authors, and identifiers tables."""
        import hashlib
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO works (
                    work_id, doi, title, publication_year, publication_date,
                    venue, publisher, volume, issue, pages, abstract,
                    citation_count, is_oa, oa_url, landing_page_url,
                    zotero_key, screening_decision, retrieval_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    work.work_id,
                    work.doi,
                    work.title,
                    work.publication_year,
                    work.publication_date,
                    work.venue,
                    work.publisher,
                    work.volume,
                    work.issue,
                    work.pages,
                    work.abstract,
                    work.citation_count,
                    1 if work.is_oa else 0,
                    work.oa_url,
                    work.landing_page_url,
                    work.zotero_key,
                    work.screening_decision.value,
                    work.retrieval_status.value,
                ),
            )

            # Authors & Authorships
            for pos, author in enumerate(work.authors, start=1):
                author_id = f"auth_{hashlib.sha256(author.name.encode('utf-8')).hexdigest()[:16]}"
                conn.execute(
                    """
                    INSERT OR IGNORE INTO authors (author_id, name, orcid, affiliation)
                    VALUES (?, ?, ?, ?)
                    """,
                    (author_id, author.name, author.orcid, author.affiliation),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO authorships (work_id, author_id, author_position)
                    VALUES (?, ?, ?)
                    """,
                    (work.work_id, author_id, pos),
                )

            # Identifiers
            for id_type, id_val in work.source_identifiers.items():
                conn.execute(
                    """
                    INSERT OR IGNORE INTO work_identifiers (work_id, identifier_type, identifier_value)
                    VALUES (?, ?, ?)
                    """,
                    (work.work_id, id_type, id_val),
                )
