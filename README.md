# mur-lab's research-engine

**Reproducible, PRISMA-traceable academic literature discovery and page-verified evidence synthesis — right from your terminal.**

`research-engine` is a local-first, human-in-the-loop CLI that connects your LLM of choice to major scholarly APIs (**OpenAlex**, **Crossref**, **Semantic Scholar**, and **Unpaywall**), your local **Zotero** library, and **PDF** full texts — storing every query, result, and verified claim in a single **SQLite** database.

---

## Why `research-engine`?

Conducting a rigorous literature review usually means juggling half a dozen browser tabs, copy-pasting queries across databases, manually deduplicating overlapping exports, losing track of PRISMA counts, and wondering whether an AI summary actually matches what a paper says.

`research-engine` solves this in one reproducible pipeline:

- **No black-box AI searches:** The AI planner turns your research question into core concepts, synonyms, competing explanations, and database-specific queries — then pauses for **your explicit approval** before a single API call runs.
- **One corpus, zero duplicates:** Results from OpenAlex, Crossref, and Semantic Scholar are automatically deduplicated (DOI → source IDs → normalized title/author/year) without overwriting richer metadata.
- **Built-in PRISMA provenance:** Every search run, result count, and newly added record is logged in SQLite so your methodology section and PRISMA flow numbers are always auditable.
- **Safe Zotero integration:** Inspects your local `zotero.sqlite` in **strict read-only mode** (`?mode=ro`) to see what you already own and stages missing papers into a clean BibTeX file for import.
- **Verified PDF evidence, not hallucinations:** Extracts 1-indexed page text with `pypdf` (flagging scanned PDFs automatically) and deterministically checks every LLM-extracted claim against the exact text on the cited page.

---

## Compatibility

| Requirement | Support |
| :--- | :--- |
| **Operating Systems** | **Linux**, **macOS**, and **Windows** |
| **Python** | **3.12+** |
| **LLM Endpoint** | Any OpenAI-compatible API (local via LiteLLM, Ollama, vLLM, or cloud) |
| **Zotero (Optional)** | Local Zotero desktop library (defaults to `~/Zotero`) |

All runtime dependencies (`httpx`, `pydantic`, `typer`, `rich`, `pypdf`, `pyyaml`, `python-dotenv`, and Python's built-in `sqlite3`) are cross-platform and MIT/BSD-compatible.

---

## Installation

### Option 1: Using `uv` (Recommended)

```bash
git clone https://github.com/mur-labs/research-engine.git
cd research-engine
uv sync
uv run research-engine --help
```

### Option 2: Using `pip` and `venv`

```bash
git clone https://github.com/mur-labs/research-engine.git
cd research-engine
python -m venv .venv
```

Activate the virtual environment:
- **Linux / macOS:** `source .venv/bin/activate`
- **Windows (PowerShell):** `.venv\Scripts\Activate.ps1`
- **Windows (cmd):** `.venv\Scripts\activate.bat`

Then install:

```bash
pip install -e .
research-engine --help
```

---

## Configuration

Copy `.env.example` to `.env` and fill in your LLM endpoint and polite-pool email:

```bash
cp .env.example .env
```

Example `.env`:

```dotenv
# OpenAI-compatible LLM endpoint (local LiteLLM/Ollama or cloud)
RESEARCH_ENGINE_LLM__API_KEY=anything
RESEARCH_ENGINE_LLM__BASE_URL=http://localhost:5000/v1
# RESEARCH_ENGINE_LLM__MODEL=smart

# Polite-pool contact email for academic APIs
RESEARCH_ENGINE_APIS__OPENALEX__EMAIL=researcher@example.com
RESEARCH_ENGINE_APIS__CROSSREF__EMAIL=researcher@example.com
RESEARCH_ENGINE_APIS__UNPAYWALL__EMAIL=researcher@example.com

# Optional overrides
# RESEARCH_ENGINE_APIS__SEMANTICSCHOLAR__API_KEY=your_key_here
# RESEARCH_ENGINE_ZOTERO__DATA_DIR=~/Zotero
```

You can also customize defaults in [config.yaml](config.yaml). Environment variables (and `.env`) take precedence over `config.yaml`.

---

## Quickstart

Check your environment and initialize the local SQLite database:

```bash
research-engine doctor
research-engine init
```

Run an end-to-end review workflow:

```bash
# 1. Generate a structured search plan (draft)
research-engine plan new "How does affective polarization affect democratic institutional trust?"

# 2. Inspect and approve the queries you want to run
research-engine plan show latest
research-engine plan approve latest

# 3. Execute approved searches across OpenAlex, Crossref, and Semantic Scholar
research-engine search execute --plan latest --limit 25

# 4. Browse or export your deduplicated corpus
research-engine works list
research-engine works export --format bibtex -o data/works_export.bib

# 5. Cross-reference with local Zotero and stage missing papers
research-engine zotero sync-status
research-engine zotero stage

# 6. Resolve Open Access PDF links via Unpaywall & inspect manual queue
research-engine access resolve
research-engine access queue

# 7. Process a PDF and extract page-verified claims
research-engine pdf process path/to/paper.pdf --work-id <work_id>
research-engine evidence extract path/to/paper.pdf --work-id <work_id>
research-engine evidence table

# 8. Run iterative gap analysis and compile the final PRISMA synthesis report
research-engine search refine --plan latest
research-engine report --plan latest -o data/research_report.md
```

For a detailed walkthrough of every step, see the **[End-to-End Workflow Tutorial](docs/tutorial.md)**.

---

## CLI Commands Overview

| Command Group | Command | Purpose |
| :--- | :--- | :--- |
| **Diagnostics** | `research-engine doctor` | Validate Python, DB, Zotero, and AI router status |
| | `research-engine init` | Initialize database tables and runtime folders |
| **Planning** | `research-engine plan new "<question>"` | Formulate theoretically grounded search plan |
| | `research-engine plan show latest` | Inspect search plan in formatted Markdown |
| | `research-engine plan approve latest` | Approve plan queries for execution |
| **Search** | `research-engine search execute --plan latest` | Query OpenAlex, Crossref, and Semantic Scholar |
| | `research-engine search results` | Review run execution logs and PRISMA counts |
| | `research-engine search refine --plan latest` | Run gap analysis and generate refinement queries |
| **Corpus** | `research-engine works list` | Browse deduplicated scholarly works |
| | `research-engine works export --format bibtex` | Export deduplicated corpus to BibTeX or CSV |
| **Zotero** | `research-engine zotero status` | Inspect local Zotero database and PDF counts |
| | `research-engine zotero sync-status` | Cross-reference works against Zotero items |
| | `research-engine zotero stage` | Stage unimported works to BibTeX file for Zotero |
| **Retrieval** | `research-engine access queue` | View/export manual institutional retrieval queue |
| | `research-engine access resolve` | Batch-resolve Open Access links via Unpaywall |
| **PDF & Evidence** | `research-engine pdf process <file.pdf>` | Extract 1-indexed page text and detect scans |
| | `research-engine evidence extract <file.pdf>` | Extract claims with verified page citations |
| | `research-engine evidence table` | Display structured evidence synthesis table |
| **Synthesis** | `research-engine report --plan latest` | Compile comprehensive PRISMA synthesis report |

---

## Development & Testing

```bash
uv run --extra dev pytest
```

## Contributing

Contributions are welcome!

1. Fork the repository and create a feature branch from `main`.
2. Install dev dependencies (`uv sync --extra dev` or `pip install -e ".[dev]"`).
3. Add or update tests for your changes and ensure `uv run --extra dev pytest` passes.
4. Keep dependencies MIT/BSD/Apache-2.0 compatible and never commit `.env`, API keys, or local `data/` files.
5. Open a pull request with a clear description of your change.

## License

This project is licensed under the MIT License (Copyright (c) 2026 `mur-labs` contributors) — see the [LICENSE](LICENSE) file for details.
