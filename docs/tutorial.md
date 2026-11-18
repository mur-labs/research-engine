# Tutorial: End-to-End Workflow with the AI-Powered Academic Research Engine

This tutorial walks through an end-to-end academic literature review workflow using the Research Engine.

## Table of Contents
1. [Prerequisites & Environment Check](#1-prerequisites--environment-check)
2. [Step 1: AI Search Strategy Planning](#2-step-1-ai-search-strategy-planning)
3. [Step 2: Inspecting and Approving the Search Plan](#3-step-2-inspecting-and-approving-the-search-plan)
4. [Step 3: Multi-API Academic Search Execution](#4-step-3-multi-api-academic-search-execution)
5. [Step 4: Corpus Inspection and Deduplication](#5-step-4-corpus-inspection-and-deduplication)
6. [Step 5: Zotero Cross-Referencing & BibTeX Staging](#6-step-5-zotero-cross-referencing--bibtex-staging)
7. [Step 6: Open Access Resolution & Retrieval Queue](#7-step-6-open-access-resolution--retrieval-queue)
8. [Step 7: PDF Document Processing & Scanned Detection](#8-step-7-pdf-document-processing--scanned-detection)
9. [Step 8: Structured Evidence Extraction & Page Verification](#9-step-8-structured-evidence-extraction--page-verification)
10. [Step 9: Iterative Search Refinement (Gap Analysis)](#10-step-9-iterative-search-refinement-gap-analysis)
11. [Step 10: Generating the Final PRISMA Synthesis Report](#11-step-10-generating-the-final-prisma-synthesis-report)

---

## 1. Prerequisites & Environment Check

Activate your virtual environment (or prefix commands with `uv run`):
```bash
cd research-engine
# Linux / macOS:
source .venv/bin/activate
# Windows (PowerShell): .venv\Scripts\Activate.ps1
```

Initialize the database and run the diagnostic tool:
```bash
research-engine init
research-engine doctor
```

Verify that:
* Python reports `OK` (3.12+).
* Database is initialized (`data/research_engine.db`).
* Zotero library is located at `~/Zotero/zotero.sqlite`.
* AI Router status is reported (either `ONLINE` or `OFFLINE / STANDBY`).

> **Tip:** Deterministic commands (`search execute`, `works list`, `works export`, `zotero status`, `zotero stage`, `pdf process`) work even when all LLM services are offline.

---

## 2. Step 1: AI Search Strategy Planning

To construct a theoretically grounded search plan from a research question:

*(Ensure your OpenAI-compatible LLM endpoint is running and configured in `.env` or `config.yaml`.)*

```bash
research-engine plan new "Does affective polarization reduce democratic institutional trust?" \
  --framework "Negative partisanship and institutional erosion" \
  --discipline "Political Science and Public Administration" \
  --mode exploratory
```

The planner uses an LLM to:
1. Identify core concepts.
2. Group true synonyms and spelling variants.
3. Distinguish related non-equivalent concepts (e.g., *negative partisanship* vs. *affective polarization*).
4. Identify competing theoretical explanations (e.g., *ideological sorting*, *economic inequality*).
5. Generate database-specific queries (`broad`, `focused`, `supplementary`).
6. Propose inclusion and exclusion screening criteria.

---

## 3. Step 2: Inspecting and Approving the Search Plan

Plans are created in `draft` status. Review the generated plan in formatted Markdown:

```bash
research-engine plan show latest
```

### Safety Approval Gate
Unapproved queries cannot be executed accidentally. To approve:

```bash
# Approve all queries in the plan:
research-engine plan approve latest

# Or selectively approve only specific queries:
research-engine plan approve latest -q plan_xxxx_q1 -q plan_xxxx_q2
```

---

## 4. Step 3: Multi-API Academic Search Execution

Execute all approved queries against academic APIs (OpenAlex, Crossref, Semantic Scholar):

```bash
research-engine search execute --plan latest --limit 25
```

The execution engine:
* Respects academic API rate limits and polite pool headers.
* Handles pagination and exponential backoff retries.
* Records each search run in `search_runs` for PRISMA accounting.
* Links raw API payloads in `search_results`.

Inspect the execution history and result counts:
```bash
research-engine search results
```

---

## 5. Step 4: Corpus Inspection and Deduplication

Retrieved records are automatically deduplicated using a strict 3-tier precedence hierarchy:
1. **Normalized DOI** (case-insensitive, URL prefixes stripped).
2. **Stable Source Identifiers** (OpenAlex ID, Semantic Scholar Corpus ID).
3. **Fuzzy Title + First Author Family Name + Publication Year** (handling ampersands, accents, and diacritics).

Browse the deduplicated corpus in your terminal:
```bash
research-engine works list --limit 20
```

Export the entire deduplicated corpus:
```bash
# Export as BibTeX:
research-engine works export --output data/corpus.bib --format bibtex

# Export as CSV (useful for spreadsheet screening):
research-engine works export --output data/corpus.csv --format csv
```

---

## 6. Step 5: Zotero Cross-Referencing & BibTeX Staging

The research engine avoids parallel PDF libraries by treating your local Zotero library as authoritative.

### Check Local Zotero Status
```bash
research-engine zotero status
```
Inspects `~/Zotero/zotero.sqlite` in safe **read-only mode** (`?mode=ro`).

### Synchronize Status
```bash
research-engine zotero sync-status
```
Cross-references every work in the research engine against your Zotero library by DOI and title. It detects whether the matching Zotero item already has an attached PDF in `storage/` and updates the work's `retrieval_status` accordingly.

### Stage Non-Duplicate Works for Zotero Import
```bash
research-engine zotero stage --output staged_import.bib
```
Exports only the candidate works that **do not already exist in your Zotero library**.

**Importing into Zotero Desktop:**
1. Open Zotero.
2. Select **File → Import...**
3. Choose **A file (BibTeX, RIS, Zotero RDF, etc.)**.
4. Select `data/zotero_exports/staged_import.bib`.

---

## 7. Step 6: Open Access Resolution & Retrieval Queue

To acquire full-text PDFs without bot protection issues:

### Batch Resolve Open Access via Unpaywall
```bash
research-engine access resolve
```
Queries `api.unpaywall.org/v2` with polite contact headers to discover legitimate Open Access PDF URLs.

### Export Manual Retrieval Queue
For paywalled literature requiring institutional authentication:
```bash
# View in terminal:
research-engine access queue

# Export to CSV:
research-engine access queue --export data/retrieval_queue.csv
```
This spreadsheet contains the direct publisher landing URLs, DOIs, titles, and authors, allowing frictionless manual downloads through university access.

---

## 8. Step 7: PDF Document Processing & Scanned Detection

When you acquire PDFs (or point to existing files):

```bash
research-engine pdf process /path/to/article.pdf
```

The processor:
1. Computes the SHA-256 hash to prevent duplicate files.
2. Extracts clean text with exact **1-indexed page boundaries**.
3. Detects if the document is **scanned or image-only** (alerting you if OCR is required).
4. Automatically matches the PDF to the corresponding work in your database by DOI or title.
5. Updates `retrieval_status` to `extraction_complete`.

---

## 9. Step 8: Structured Evidence Extraction & Page Verification

Extract empirical claims, methodology, and verified passage links from processed documents:

```bash
research-engine evidence extract /path/to/article.pdf \
  --work-id <work_id> \
  --question "Does affective polarization reduce democratic institutional trust?"
```

### Deterministic Verification Guardrail
The engine enforces that:
* Cited page numbers exist in the PDF structure.
* Quoted verbatim text actually appears on that specific page in the document.
* If a quote is not found, it is marked with an `⚠ Unverified` badge instead of being reported as verified evidence.

Display the structured evidence synthesis table:
```bash
research-engine evidence table
```

---

## 10. Step 9: Iterative Search Refinement (Gap Analysis)

After retrieving initial search results, evaluate coverage gaps:

```bash
research-engine search refine --plan latest --budget 5
```

The refiner:
1. Compares the retrieved literature against the original research question.
2. Detects uncaptured scholarly terminology.
3. Identifies geographic, disciplinary, or theoretical coverage gaps.
4. Evaluates stopping rules based on remaining search budget and marginal relevant returns.
5. Saves versioned supplementary queries to a new plan version (e.g. `v2`).

Approve the supplementary queries before running them:
```bash
research-engine plan approve latest
research-engine search execute --plan latest
```

---

## 11. Step 10: Generating the Final PRISMA Synthesis Report

Compile a complete, reproducible research synthesis:

```bash
research-engine report --plan latest --output data/research_report.md
```

The generated report documents:
* **PRISMA Search Flow Accounting:** Exact query strings, database result counts, retrieved records, and unique additions.
* **Concept Mapping:** Core concepts, synonyms, related concepts, and competing explanations.
* **Full-Text Retrieval Status:** Accessible PDFs vs. institutional queue.
* **Evidence Synthesis Table:** Categorized claims (`direct_quotation`, `author_conclusion`, `faithful_paraphrase`) with exact page citations and verification status.
* **Methodological Limitations:** Explicit notes on coverage boundaries and database constraints.
