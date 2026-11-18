"""Command-line interface for the AI-Powered Academic Research Engine."""

import sys
from pathlib import Path
import typer
from rich.console import Console
from rich.table import Table

from research_engine import __version__
from research_engine.config import AppConfig, load_config
from research_engine.database import DatabaseManager

app = typer.Typer(
    name="research-engine",
    help="AI-Powered Academic Research Engine: Plan, search, manage and synthesize academic research.",
    no_args_is_help=True,
)
console = Console()


def _require_db(cfg: AppConfig) -> DatabaseManager:
    """Return an initialized DatabaseManager or exit cleanly with guidance."""
    if not Path(cfg.database.path).is_file():
        console.print("[bold red]Database not initialized.[/bold red] Run [bold]research-engine init[/bold] first.")
        raise typer.Exit(code=1)
    db_mgr = DatabaseManager(cfg.database.path)
    if db_mgr.get_applied_version() == 0:
        console.print("[bold red]Database schema not initialized.[/bold red] Run [bold]research-engine init[/bold] first.")
        raise typer.Exit(code=1)
    return db_mgr


@app.command()
def version() -> None:
    """Show the research-engine version."""
    console.print(f"[bold green]research-engine[/bold green] version [cyan]{__version__}[/cyan]")


@app.command()
def init(
    config_path: Path = typer.Option(
        Path("config.yaml"),
        "--config",
        "-c",
        help="Path to configuration file.",
    ),
) -> None:
    """Initialize local database and directory structure."""
    try:
        cfg = load_config(config_path)
        db_mgr = DatabaseManager(cfg.database.path)
        db_mgr.initialize_schema()

        # Ensure runtime folders exist
        cfg.retrieval.pdf_storage_dir.mkdir(parents=True, exist_ok=True)
        cfg.zotero.bibtex_export_dir.mkdir(parents=True, exist_ok=True)
        Path("logs").mkdir(parents=True, exist_ok=True)

        current_v = db_mgr.get_applied_version()
        console.print(f"[bold green]✓[/bold green] Database initialized at: [cyan]{cfg.database.path}[/cyan] (Schema v{current_v})")
        console.print(f"[bold green]✓[/bold green] PDF storage directory ready: [cyan]{cfg.retrieval.pdf_storage_dir}[/cyan]")
        console.print(f"[bold green]✓[/bold green] BibTeX export directory ready: [cyan]{cfg.zotero.bibtex_export_dir}[/cyan]")
    except Exception as e:
        console.print(f"[bold red]✗ Initialization error:[/bold red] {e}")
        raise typer.Exit(code=1)


@app.command()
def doctor(
    config_path: Path = typer.Option(
        Path("config.yaml"),
        "--config",
        "-c",
        help="Path to configuration file.",
    ),
) -> None:
    """Check environment, dependencies, database, and local service availability."""
    console.print(f"[bold blue]Checking Research Engine Environment (v{__version__})...[/bold blue]\n")

    table = Table(title="System Diagnostics", show_header=True, header_style="bold magenta")
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Details")

    # 1. Python version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 12):
        table.add_row("Python", "[green]OK[/green]", f"Python {py_ver}")
    else:
        table.add_row("Python", "[yellow]WARNING[/yellow]", f"Python {py_ver} (Recommend 3.12+)")

    # 2. Configuration file
    try:
        cfg = load_config(config_path)
        cfg_status = "[green]OK[/green]" if config_path.is_file() else "[yellow]DEFAULT[/yellow]"
        table.add_row("Configuration", cfg_status, f"Loaded from {config_path}")
    except Exception as err:
        table.add_row("Configuration", "[red]ERROR[/red]", str(err))
        cfg = None

    # 3. Database
    if cfg:
        db_mgr = DatabaseManager(cfg.database.path)
        schema_v = db_mgr.get_applied_version()
        if schema_v > 0:
            table.add_row("Database", "[green]OK[/green]", f"{cfg.database.path} (Schema v{schema_v})")
        else:
            table.add_row("Database", "[yellow]NOT INITIALIZED[/yellow]", "Run 'research-engine init'")

    # 4. Zotero Data Directory
    if cfg:
        zotero_db = cfg.zotero.data_dir / "zotero.sqlite"
        if zotero_db.is_file():
            table.add_row("Zotero Library", "[green]FOUND[/green]", f"{zotero_db} (Local read ready)")
        else:
            table.add_row("Zotero Library", "[yellow]NOT FOUND[/yellow]", f"{zotero_db} does not exist")

    # 5. Local AI Router / LiteLLM Reachability
    if cfg:
        import httpx
        try:
            r = httpx.get(f"{cfg.llm.base_url.rstrip('/')}/models", timeout=2.0)
            if r.status_code == 200:
                table.add_row("AI Router", "[green]ONLINE[/green]", f"{cfg.llm.base_url}")
            else:
                table.add_row("AI Router", "[yellow]HTTP ERROR[/yellow]", f"{cfg.llm.base_url} returned {r.status_code}")
        except Exception:
            table.add_row("AI Router", "[dim]OFFLINE / STANDBY[/dim]", f"{cfg.llm.base_url} (Deterministic fallback active)")

    console.print(table)


plan_app = typer.Typer(help="Manage AI-generated research plans and search strategies.")
app.add_typer(plan_app, name="plan")


@plan_app.command("new")
def plan_new(
    question: str = typer.Argument(..., help="Natural language research question."),
    framework: str | None = typer.Option(None, "--framework", "-f", help="Theoretical framework."),
    discipline: str = typer.Option("Political Science and Public Administration", "--discipline", "-d", help="Discipline scope."),
    mode: str = typer.Option("exploratory", "--mode", "-m", help="Review mode (exploratory / systematic)."),
    config_path: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Config file."),
) -> None:
    """Generate a new AI search strategy from a research question."""
    from research_engine.llm import LLMClient
    from research_engine.planner import ResearchPlanner
    from research_engine.models import ReviewMode

    try:
        cfg = load_config(config_path)
        db_mgr = DatabaseManager(cfg.database.path)
        db_mgr.initialize_schema()

        llm = LLMClient(cfg.llm)
        planner = ResearchPlanner(db_mgr, llm)

        rev_mode = ReviewMode.SYSTEMATIC if mode.lower() == "systematic" else ReviewMode.EXPLORATORY

        with console.status(f"[bold cyan]Formulating search plan for:[/bold cyan] '{question}'..."):
            plan = planner.generate_plan(
                research_question=question,
                theoretical_framework=framework,
                discipline_scope=discipline,
                review_mode=rev_mode,
            )

        console.print(f"\n[bold green]✓ Search plan generated successfully![/bold green]")
        console.print(f"Plan ID: [cyan]{plan.plan_id}[/cyan] (v{plan.version}) - Status: [yellow]{plan.status.value}[/yellow]")
        console.print(f"Proposed queries: [bold]{len(plan.queries)}[/bold]")
        console.print("\nRun [bold]research-engine plan show latest[/bold] to inspect the full plan.")
        console.print("Run [bold]research-engine plan approve latest[/bold] to approve it for execution.")
    except Exception as e:
        console.print(f"[bold red]✗ Plan generation failed:[/bold red] {e}")
        raise typer.Exit(code=1)


@plan_app.command("show")
def plan_show(
    plan_id: str = typer.Argument("latest", help="Plan ID or 'latest'."),
    config_path: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Config file."),
) -> None:
    """Show details of a search plan."""
    from research_engine.llm import LLMClient
    from research_engine.planner import ResearchPlanner

    cfg = load_config(config_path)
    db_mgr = _require_db(cfg)
    llm = LLMClient(cfg.llm)
    planner = ResearchPlanner(db_mgr, llm)

    plan = planner.get_latest_plan() if plan_id == "latest" else planner.get_plan(plan_id)
    if not plan:
        console.print(f"[bold red]Plan '{plan_id}' not found.[/bold red]")
        raise typer.Exit(code=1)

    md = planner.export_plan_markdown(plan)
    console.print(md)


@plan_app.command("approve")
def plan_approve(
    plan_id: str = typer.Argument("latest", help="Plan ID or 'latest'."),
    query_id: list[str] | None = typer.Option(None, "--query", "-q", help="Specific query ID(s) to approve (default: all)."),
    config_path: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Config file."),
) -> None:
    """Approve a draft search plan for execution."""
    from research_engine.llm import LLMClient
    from research_engine.planner import ResearchPlanner

    cfg = load_config(config_path)
    db_mgr = _require_db(cfg)
    llm = LLMClient(cfg.llm)
    planner = ResearchPlanner(db_mgr, llm)

    target_plan = planner.get_latest_plan() if plan_id == "latest" else planner.get_plan(plan_id)
    if not target_plan:
        console.print(f"[bold red]Plan '{plan_id}' not found.[/bold red]")
        raise typer.Exit(code=1)

    updated = planner.approve_plan(target_plan.plan_id, query_ids=query_id)
    approved_count = sum(1 for q in updated.queries if q.is_approved)

    console.print(f"[bold green]✓ Plan {updated.plan_id} approved![/bold green]")
    console.print(f"Approved queries: [bold cyan]{approved_count}/{len(updated.queries)}[/bold cyan]")


search_app = typer.Typer(help="Execute approved searches and inspect run logs.")
app.add_typer(search_app, name="search")


@search_app.command("execute")
def search_execute(
    plan_id: str = typer.Option("latest", "--plan", "-p", help="Plan ID to execute (or 'latest')."),
    limit: int = typer.Option(25, "--limit", "-l", help="Max records retrieved per query."),
    config_path: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Config file."),
) -> None:
    """Execute all approved queries in a search plan."""
    from research_engine.llm import LLMClient
    from research_engine.planner import ResearchPlanner
    from research_engine.search import SearchExecutor

    cfg = load_config(config_path)
    db_mgr = _require_db(cfg)
    planner = ResearchPlanner(db_mgr, LLMClient(cfg.llm))

    plan = planner.get_latest_plan() if plan_id == "latest" else planner.get_plan(plan_id)
    if not plan:
        console.print(f"[bold red]Plan '{plan_id}' not found.[/bold red]")
        raise typer.Exit(code=1)

    executor = SearchExecutor(db_mgr, cfg)

    with console.status(f"[bold cyan]Executing searches for plan {plan.plan_id}...[/bold cyan]"):
        try:
            runs = executor.execute_plan(plan, limit_per_query=limit)
        except Exception as e:
            console.print(f"[bold red]Execution error:[/bold red] {e}")
            raise typer.Exit(code=1)

    table = Table(title=f"Search Execution Results ({plan.plan_id})", show_header=True)
    table.add_column("Run ID", style="cyan")
    table.add_column("Database", style="magenta")
    table.add_column("Found", justify="right")
    table.add_column("Retrieved", justify="right")
    table.add_column("New Added", justify="right", style="green")
    table.add_column("Status")

    for r in runs:
        status_str = f"[red]{r.error_message}[/red]" if r.error_message else "[green]SUCCESS[/green]"
        table.add_row(
            r.run_id,
            r.target_database,
            str(r.total_results_found),
            str(r.records_retrieved),
            str(r.new_records_added),
            status_str,
        )

    console.print(table)


@search_app.command("results")
def search_results(
    plan_id: str | None = typer.Option(None, "--plan", "-p", help="Filter by plan ID."),
    config_path: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Config file."),
) -> None:
    """Show execution history and PRISMA search accounting."""
    from research_engine.provenance import ProvenanceTracker

    cfg = load_config(config_path)
    db_mgr = _require_db(cfg)
    tracker = ProvenanceTracker(db_mgr)
    summary = tracker.get_run_summary(plan_id=plan_id)

    if not summary:
        console.print("[yellow]No search runs found.[/yellow]")
        return

    table = Table(title="Search Run History", show_header=True)
    table.add_column("Run ID", style="cyan")
    table.add_column("Plan ID")
    table.add_column("DB", style="magenta")
    table.add_column("Total Found", justify="right")
    table.add_column("Retrieved", justify="right")
    table.add_column("New", justify="right", style="green")
    table.add_column("Executed At")

    for row in summary:
        table.add_row(
            row["run_id"],
            row["plan_id"],
            row["target_database"],
            str(row["total_results_found"]),
            str(row["records_retrieved"]),
            str(row["new_records_added"]),
            str(row["executed_at"])[:19],
        )

    console.print(table)


works_app = typer.Typer(help="Browse and export scholarly works corpus.")
app.add_typer(works_app, name="works")


@works_app.command("list")
def works_list(
    limit: int = typer.Option(20, "--limit", "-l", help="Number of records to show."),
    config_path: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Config file."),
) -> None:
    """List scholarly works currently in the research database."""
    cfg = load_config(config_path)
    db_mgr = _require_db(cfg)

    with db_mgr.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT work_id, doi, title, publication_year, venue, is_oa, retrieval_status
            FROM works
            ORDER BY publication_year DESC, title ASC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()

    if not rows:
        console.print("[yellow]Database is currently empty. Run searches first.[/yellow]")
        return

    table = Table(title=f"Scholarly Corpus (showing {len(rows)})", show_header=True)
    table.add_column("Work ID", style="cyan")
    table.add_column("Year", justify="right")
    table.add_column("Title")
    table.add_column("Venue", style="magenta")
    table.add_column("OA", justify="center")
    table.add_column("Retrieval Status")

    for r in rows:
        oa_str = "[green]YES[/green]" if r["is_oa"] else "NO"
        title_disp = r["title"][:50] + ("..." if len(r["title"]) > 50 else "")
        venue_disp = (r["venue"] or "")[:25]
        table.add_row(
            r["work_id"],
            str(r["publication_year"] or ""),
            title_disp,
            venue_disp,
            oa_str,
            r["retrieval_status"],
        )

    console.print(table)


@works_app.command("export")
def works_export(
    output: Path = typer.Option(Path("data/works_export.bib"), "--output", "-o", help="Output file path."),
    fmt: str = typer.Option("bibtex", "--format", "-f", help="Export format: bibtex or csv."),
    config_path: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Config file."),
) -> None:
    """Export deduplicated scholarly works to BibTeX or CSV."""
    from research_engine.deduplication.engine import DeduplicationEngine
    from research_engine.export import export_works_to_bibtex, export_works_to_csv

    cfg = load_config(config_path)
    db_mgr = _require_db(cfg)
    dedup = DeduplicationEngine(db_mgr)

    with db_mgr.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT work_id FROM works")
        ids = [r["work_id"] for r in cursor.fetchall()]

    works = [dedup._load_work_by_id(w_id) for w_id in ids]
    valid_works = [w for w in works if w is not None]

    if fmt.lower() == "csv":
        export_works_to_csv(valid_works, output)
    else:
        export_works_to_bibtex(valid_works, output)

    console.print(f"[bold green]✓ Exported {len(valid_works)} records to [cyan]{output}[/cyan][/bold green]")


zotero_app = typer.Typer(help="Inspect local Zotero library and stage BibTeX imports.")
app.add_typer(zotero_app, name="zotero")


@zotero_app.command("status")
def zotero_status(
    config_path: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Config file."),
) -> None:
    """Inspect local Zotero database and attachment statistics."""
    from research_engine.zotero import LocalZoteroReader

    cfg = load_config(config_path)
    reader = LocalZoteroReader(cfg.zotero.data_dir)

    if not reader.is_available():
        console.print(f"[bold red]Zotero SQLite database not found at {reader.sqlite_path}[/bold red]")
        raise typer.Exit(code=1)

    summary = reader.get_library_summary()
    table = Table(title="Local Zotero Library Status", show_header=True)
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="bold green")

    table.add_row("Database Path", summary["sqlite_path"])
    table.add_row("Storage Path", summary["storage_dir"])
    table.add_row("Regular Scholarly Items", str(summary["total_regular_items"]))
    table.add_row("PDF Attachments", str(summary["total_pdf_attachments"]))

    console.print(table)


@zotero_app.command("sync-status")
def zotero_sync_status(
    config_path: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Config file."),
) -> None:
    """Cross-reference works in research database with local Zotero library."""
    from research_engine.zotero import LocalZoteroReader, ZoteroStagingManager

    cfg = load_config(config_path)
    db_mgr = _require_db(cfg)
    reader = LocalZoteroReader(cfg.zotero.data_dir)
    staging = ZoteroStagingManager(db_mgr, reader, cfg.zotero.bibtex_export_dir)

    with console.status("[bold cyan]Cross-referencing database with local Zotero...[/bold cyan]"):
        try:
            stats = staging.sync_local_status()
        except Exception as e:
            console.print(f"[bold red]Sync error:[/bold red] {e}")
            raise typer.Exit(code=1)

    table = Table(title="Zotero Synchronization Summary", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="bold")

    table.add_row("Total Works in Research DB", str(stats["total_works"]))
    table.add_row("Matched in Zotero", f"[green]{stats['matched_in_zotero']}[/green]")
    table.add_row("With Full-Text PDF in Zotero", f"[green]{stats['with_pdf_in_zotero']}[/green]")
    table.add_row("Unlinked / Missing from Zotero", f"[yellow]{stats['missing_from_zotero']}[/yellow]")

    console.print(table)


@zotero_app.command("stage")
def zotero_stage(
    output: str = typer.Option("staged_import.bib", "--output", "-o", help="Output filename in zotero_exports dir."),
    all_records: bool = typer.Option(False, "--all", "-a", help="Export all records, including already linked."),
    config_path: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Config file."),
) -> None:
    """Stage unimported research records to a clean BibTeX file for Zotero import."""
    from research_engine.zotero import LocalZoteroReader, ZoteroStagingManager

    cfg = load_config(config_path)
    db_mgr = _require_db(cfg)
    reader = LocalZoteroReader(cfg.zotero.data_dir)
    staging = ZoteroStagingManager(db_mgr, reader, cfg.zotero.bibtex_export_dir)

    out_path, count = staging.stage_bibtex_import(
        output_filename=output,
        only_unlinked=not all_records,
    )

    console.print(f"[bold green]✓ Staged {count} records for Zotero import:[/bold green] [cyan]{out_path}[/cyan]")
    console.print("Import in Zotero: [dim]File -> Import -> select staged_import.bib[/dim]")


access_app = typer.Typer(help="Manage full-text access queue and Open Access resolution.")
app.add_typer(access_app, name="access")


@access_app.command("queue")
def access_queue(
    export_csv: Path | None = typer.Option(None, "--export", "-e", help="Export queue to CSV file path."),
    config_path: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Config file."),
) -> None:
    """View or export candidate papers awaiting full-text acquisition."""
    from research_engine.retrieval import RetrievalQueueManager

    cfg = load_config(config_path)
    db_mgr = _require_db(cfg)
    qm = RetrievalQueueManager(db_mgr)

    if export_csv:
        path, count = qm.export_retrieval_queue_csv(export_csv)
        console.print(f"[bold green]✓ Exported {count} retrieval candidate(s) to [cyan]{path}[/cyan][/bold green]")
        return

    candidates = qm.get_retrieval_candidates(only_missing=True)
    if not candidates:
        console.print("[green]No pending papers in retrieval queue! All papers have full text or are excluded.[/green]")
        return

    table = Table(title=f"Full-Text Retrieval Queue ({len(candidates)} pending)", show_header=True)
    table.add_column("Work ID", style="cyan")
    table.add_column("Year", justify="right")
    table.add_column("Title")
    table.add_column("DOI", style="magenta")
    table.add_column("OA Found", justify="center")
    table.add_column("Status")

    for w in candidates[:25]:
        oa_str = "[green]YES[/green]" if w.is_oa else "NO"
        title_disp = w.title[:45] + ("..." if len(w.title) > 45 else "")
        table.add_row(
            w.work_id,
            str(w.publication_year or ""),
            title_disp,
            w.doi or "—",
            oa_str,
            w.retrieval_status.value,
        )

    console.print(table)


@access_app.command("resolve")
def access_resolve(
    config_path: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Config file."),
) -> None:
    """Query Unpaywall to find open-access versions for pending works."""
    from research_engine.retrieval import RetrievalQueueManager, UnpaywallResolver

    cfg = load_config(config_path)
    db_mgr = _require_db(cfg)
    unpaywall = UnpaywallResolver(cfg.apis.unpaywall)
    qm = RetrievalQueueManager(db_mgr, unpaywall)

    with console.status("[bold cyan]Resolving Open Access locations via Unpaywall...[/bold cyan]"):
        try:
            stats = qm.resolve_open_access_batch()
        except Exception as e:
            console.print(f"[bold red]Resolution error:[/bold red] {e}")
            raise typer.Exit(code=1)

    console.print(f"[bold green]✓ Checked {stats['candidates_checked']} candidates.[/bold green]")
    console.print(f"Found OA URLs for: [bold cyan]{stats['oa_locations_found']}[/bold cyan] record(s)")


pdf_app = typer.Typer(help="Process full-text PDFs and extract page structure.")
app.add_typer(pdf_app, name="pdf")


@pdf_app.command("process")
def pdf_process(
    file_path: Path = typer.Argument(..., help="Path to PDF file to process."),
    work_id: str | None = typer.Option(None, "--work-id", "-w", help="Target work ID to associate with."),
    config_path: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Config file."),
) -> None:
    """Extract text and page numbers from a PDF document."""
    from research_engine.pdf import PDFProcessor

    cfg = load_config(config_path)
    db_mgr = _require_db(cfg)
    processor = PDFProcessor(db_mgr, cfg.retrieval.pdf_storage_dir, cfg.retrieval.max_pdf_size_mb)

    with console.status(f"[bold cyan]Processing PDF {file_path.name}...[/bold cyan]"):
        work, result = processor.import_and_match_pdf(file_path, target_work_id=work_id)

    if result.error_message:
        console.print(f"[bold red]✗ Processing failed:[/bold red] {result.error_message}")
        raise typer.Exit(code=1)

    table = Table(title="PDF Processing Summary", show_header=True)
    table.add_column("Property", style="cyan")
    table.add_column("Value")

    table.add_row("Pages Extracted", str(result.page_count))
    table.add_row("Total Characters", str(result.total_characters))
    table.add_row("Scanned / Image-only", "[red]YES[/red]" if result.is_scanned else "[green]NO[/green]")
    table.add_row("File SHA-256", result.file_hash[:16] + "...")
    if work:
        table.add_row("Matched Work ID", f"[green]{work.work_id}[/green] ({work.title[:40]}...)")
    else:
        table.add_row("Matched Work", "[yellow]Unmatched (standalone processing)[/yellow]")

    console.print(table)


evidence_app = typer.Typer(help="Extract and verify page-referenced evidence from documents.")
app.add_typer(evidence_app, name="evidence")


@evidence_app.command("extract")
def evidence_extract(
    pdf_path: Path = typer.Argument(..., help="Path to PDF document."),
    work_id: str = typer.Option(..., "--work-id", "-w", help="Target work ID in research database."),
    question: str | None = typer.Option(None, "--question", "-q", help="Guiding research question."),
    config_path: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Config file."),
) -> None:
    """Extract structured claims and verify page citations from a document."""
    from research_engine.evidence import EvidenceExtractor
    from research_engine.llm import LLMClient
    from research_engine.pdf import PDFProcessor
    from research_engine.deduplication.engine import DeduplicationEngine

    cfg = load_config(config_path)
    db_mgr = _require_db(cfg)
    dedup = DeduplicationEngine(db_mgr)
    work = dedup._load_work_by_id(work_id)

    if not work:
        console.print(f"[bold red]Work '{work_id}' not found in database.[/bold red]")
        raise typer.Exit(code=1)

    processor = PDFProcessor(db_mgr, cfg.retrieval.pdf_storage_dir)
    pdf_res = processor.process_pdf(pdf_path)

    if pdf_res.error_message:
        console.print(f"[bold red]Cannot process PDF:[/bold red] {pdf_res.error_message}")
        raise typer.Exit(code=1)

    llm = LLMClient(cfg.llm)
    extractor = EvidenceExtractor(db_mgr, llm)

    with console.status(f"[bold cyan]Extracting and verifying evidence for {work.title[:40]}...[/bold cyan]"):
        try:
            records = extractor.extract_evidence(work, pdf_res, research_question=question)
        except Exception as e:
            console.print(f"[bold red]Extraction error:[/bold red] {e}")
            raise typer.Exit(code=1)

    console.print(f"[bold green]✓ Extracted {len(records)} evidence claim(s) successfully![/bold green]")
    for r in records:
        ver_badge = "[green]✓ Verified[/green]" if r["is_verified"] else "[yellow]⚠ Unverified[/yellow]"
        console.print(f"- [bold]{r['claim_type']}[/bold] (Page {r['page_start']}): {r['content'][:80]}... {ver_badge}")


@evidence_app.command("table")
def evidence_table(
    work_id: str | None = typer.Option(None, "--work-id", "-w", help="Filter by specific work ID."),
    config_path: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Config file."),
) -> None:
    """Display structured evidence synthesis table."""
    from research_engine.evidence import EvidenceExtractor
    from research_engine.llm import LLMClient

    cfg = load_config(config_path)
    db_mgr = _require_db(cfg)
    extractor = EvidenceExtractor(db_mgr, LLMClient(cfg.llm))

    records = extractor.get_evidence_table(work_id=work_id)
    if not records:
        console.print("[yellow]No evidence records found. Run 'research-engine evidence extract' first.[/yellow]")
        return

    table = Table(title=f"Structured Evidence Synthesis ({len(records)} claims)", show_header=True)
    table.add_column("Type", style="cyan")
    table.add_column("Claim / Finding")
    table.add_column("Page", justify="center")
    table.add_column("Supporting Passage", style="dim")
    table.add_column("Verified", justify="center")

    for r in records:
        ver_str = "[green]YES[/green]" if r["is_verified"] else "[yellow]NO[/yellow]"
        passage_disp = (r["supporting_passage"] or "")[:45] + "..." if r["supporting_passage"] else "—"
        table.add_row(
            r["claim_type"],
            r["content"][:60] + "...",
            str(r["page_start"]),
            passage_disp,
            ver_str,
        )

    console.print(table)


@search_app.command("refine")
def search_refine(
    plan_id: str = typer.Option("latest", "--plan", "-p", help="Plan ID to analyze and refine."),
    budget: int = typer.Option(5, "--budget", "-b", help="Maximum search run budget."),
    config_path: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Config file."),
) -> None:
    """Analyze actual results, detect theoretical gaps, and propose refinement queries."""
    from research_engine.llm import LLMClient
    from research_engine.planner.generator import ResearchPlanner
    from research_engine.planner.refiner import SearchRefiner

    cfg = load_config(config_path)
    db_mgr = _require_db(cfg)
    llm = LLMClient(cfg.llm)
    planner = ResearchPlanner(db_mgr, llm)

    target_plan = planner.get_latest_plan() if plan_id == "latest" else planner.get_plan(plan_id)
    if not target_plan:
        console.print(f"[bold red]Plan '{plan_id}' not found.[/bold red]")
        raise typer.Exit(code=1)

    refiner = SearchRefiner(db_mgr, llm)

    with console.status(f"[bold cyan]Analyzing results and coverage gaps for plan {target_plan.plan_id}...[/bold cyan]"):
        try:
            analysis, updated_plan = refiner.analyze_and_refine(target_plan, budget_limit=budget)
        except Exception as e:
            console.print(f"[bold red]Refinement error:[/bold red] {e}")
            raise typer.Exit(code=1)

    console.print(f"\n[bold green]✓ Gap Analysis Complete (Updated Plan v{updated_plan.version})[/bold green]")
    console.print(f"Stopping Rule Met: {'[bold yellow]YES[/bold yellow]' if analysis.stop_recommendation else '[bold green]NO (Additional search recommended)[/bold green]'}")
    console.print(f"Reason: [dim]{analysis.stop_reason}[/dim]\n")

    if analysis.coverage_gaps:
        console.print("[bold]Identified Coverage Gaps:[/bold]")
        for g in analysis.coverage_gaps:
            console.print(f"- {g}")

    if analysis.missed_vocabulary:
        console.print("\n[bold]Missed Scholarly Vocabulary:[/bold]")
        for v in analysis.missed_vocabulary:
            console.print(f"- {v}")

    supp_count = len(updated_plan.queries) - len(target_plan.queries)
    console.print(f"\nProposed [bold cyan]{supp_count}[/bold cyan] supplementary queries saved to plan v{updated_plan.version}.")
    console.print("Run [bold]research-engine plan approve latest[/bold] to review and approve them before execution.")


@app.command("report")
def generate_report(
    plan_id: str = typer.Option("latest", "--plan", "-p", help="Plan ID to report on."),
    output: Path = typer.Option(Path("data/research_report.md"), "--output", "-o", help="Output Markdown report path."),
    config_path: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Config file."),
) -> None:
    """Generate comprehensive synthesis report with PRISMA flow and verified evidence."""
    from research_engine.llm import LLMClient
    from research_engine.planner.generator import ResearchPlanner
    from research_engine.export.report import ResearchReportGenerator

    cfg = load_config(config_path)
    db_mgr = _require_db(cfg)
    planner = ResearchPlanner(db_mgr, LLMClient(cfg.llm))

    plan = planner.get_latest_plan() if plan_id == "latest" else planner.get_plan(plan_id)
    if not plan:
        console.print(f"[bold red]Plan '{plan_id}' not found.[/bold red]")
        raise typer.Exit(code=1)

    gen = ResearchReportGenerator(db_mgr)
    md = gen.generate_report(plan, output_path=output)

    console.print(f"[bold green]✓ Research Synthesis Report generated successfully![/bold green]")
    console.print(f"Report saved to: [cyan]{output}[/cyan]")


if __name__ == "__main__":
    app()






