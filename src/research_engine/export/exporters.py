"""Exporters for scholarly works (CSV, JSON, BibTeX)."""

import csv
import json
from pathlib import Path
import re
from typing import TextIO
from research_engine.models import Work


def export_works_to_csv(works: list[Work], output_file: Path | str) -> None:
    """Export scholarly works list to CSV file."""
    path = Path(output_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "work_id",
        "doi",
        "title",
        "authors",
        "publication_year",
        "venue",
        "publisher",
        "citation_count",
        "is_oa",
        "oa_url",
        "retrieval_status",
        "screening_decision",
    ]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for w in works:
            authors_str = "; ".join(a.name for a in w.authors)
            writer.writerow(
                {
                    "work_id": w.work_id,
                    "doi": w.doi or "",
                    "title": w.title,
                    "authors": authors_str,
                    "publication_year": w.publication_year or "",
                    "venue": w.venue or "",
                    "publisher": w.publisher or "",
                    "citation_count": w.citation_count or 0,
                    "is_oa": "Yes" if w.is_oa else "No",
                    "oa_url": w.oa_url or "",
                    "retrieval_status": w.retrieval_status.value,
                    "screening_decision": w.screening_decision.value,
                }
            )


def export_works_to_bibtex(works: list[Work], output_file: Path | str) -> None:
    """Export scholarly works list to standard BibTeX format."""
    path = Path(output_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    used_keys: set[str] = set()
    with open(path, "w", encoding="utf-8") as f:
        for w in works:
            # Generate stable citation key: FirstAuthorYearTitleToken
            first_author = ""
            if w.authors and w.authors[0].name:
                tokens = re.sub(r"[^\w\s]", "", w.authors[0].name).split()
                first_author = tokens[-1].lower() if tokens else "anon"
            else:
                first_author = "anon"

            year_str = str(w.publication_year) if w.publication_year else "nodate"
            title_words = re.sub(r"[^\w\s]", "", w.title).split()
            first_word = title_words[0].lower() if title_words else "item"

            base_key = f"{first_author}{year_str}_{first_word}"
            cite_key = base_key
            suffix = 2
            while cite_key in used_keys:
                cite_key = f"{base_key}_{suffix}"
                suffix += 1
            used_keys.add(cite_key)
            authors_str = " and ".join(a.name for a in w.authors)

            entry_type = "article" if w.venue else "misc"
            f.write(f"@{entry_type}{{{cite_key},\n")
            f.write(f"  title = {{{w.title}}},\n")
            if authors_str:
                f.write(f"  author = {{{authors_str}}},\n")
            if w.publication_year:
                f.write(f"  year = {{{w.publication_year}}},\n")
            if w.venue:
                f.write(f"  journal = {{{w.venue}}},\n")
            if w.volume:
                f.write(f"  volume = {{{w.volume}}},\n")
            if w.issue:
                f.write(f"  number = {{{w.issue}}},\n")
            if w.pages:
                f.write(f"  pages = {{{w.pages}}},\n")
            if w.doi:
                f.write(f"  doi = {{{w.doi}}},\n")
            if w.oa_url or w.landing_page_url:
                url = w.oa_url or w.landing_page_url
                f.write(f"  url = {{{url}}},\n")
            f.write("}\n\n")
