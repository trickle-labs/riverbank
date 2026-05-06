from __future__ import annotations

import typer
from rich import print as rprint
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from riverbank import __version__
from riverbank.config import get_settings

app = typer.Typer(
    name="riverbank",
    help="Compiled knowledge-base worker for pg-ripple + pg-trickle + pg-tide.",
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    """Print the riverbank version."""
    rprint(f"riverbank [bold]{__version__}[/bold]")


@app.command()
def config() -> None:
    """Show the current configuration (resolved from env and config.toml)."""
    settings = get_settings()
    table = Table(title="riverbank configuration", show_header=True, header_style="bold cyan")
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Value")

    table.add_row("db.dsn", settings.db.dsn)
    table.add_row("llm.provider", settings.llm.provider)
    table.add_row("llm.api_base", settings.llm.api_base)
    table.add_row("llm.model", settings.llm.model)
    table.add_row("llm.embed_model", settings.llm.embed_model)
    table.add_row("langfuse.enabled", str(settings.langfuse.enabled))
    table.add_row("langfuse.host", settings.langfuse.host)

    rprint(table)


@app.command()
def health() -> None:
    """Run health checks against the full extension stack.

    Calls pgtrickle.preflight() (7 system checks) and
    pg_ripple.pg_tide_available() to verify pg-tide is wired correctly.
    """
    import psycopg  # noqa: PLC0415 — import here to keep startup fast

    settings = get_settings()
    all_ok = True

    rprint("[bold]riverbank health check[/bold]\n")

    # psycopg uses the standard postgresql:// scheme (no +psycopg suffix)
    dsn = settings.db.dsn.replace("postgresql+psycopg://", "postgresql://")

    try:
        import json  # noqa: PLC0415
        
        with psycopg.connect(dsn) as conn:
            # pg-trickle preflight — returns JSON object with check results
            result = conn.execute("SELECT * FROM pgtrickle.preflight()").fetchone()
            if result:
                preflight_data = result[0]
                # Handle both JSON string and dict formats
                if isinstance(preflight_data, str):
                    checks = json.loads(preflight_data)
                else:
                    checks = preflight_data
                
                # Checks that are critical for operation
                critical_checks = {"scheduler_running", "wal_level"}
                
                for check_name, check_info in checks.items():
                    ok = check_info.get("ok", False)
                    detail = check_info.get("detail", "")
                    icon = "[green]✓[/green]" if ok else "[red]✗[/red]"
                    rprint(f"  {icon}  pg_trickle  {check_name:<32} {detail}")
                    # Only fail health check on critical pg_trickle issues
                    if not ok and check_name in critical_checks:
                        all_ok = False

            # pg-ripple pg_tide availability check
            result = conn.execute("SELECT pg_ripple.pg_tide_available()").fetchone()
            available = result[0] if result else False
            icon = "[green]✓[/green]" if available else "[yellow]![/yellow]"
            note = "yes" if available else "no (pg-tide sidecar not detected)"
            rprint(f"  {icon}  pg_ripple   pg_tide_available                {note}")
            if not available:
                rprint(
                    "       [dim]pg-tide is optional — CDC relay features will be unavailable"
                    "[/dim]"
                )

    except Exception as exc:
        rprint(f"  [red]✗[/red]  database connection failed: {exc}")
        all_ok = False

    # v0.7.0: circuit breaker status for LLM providers
    from riverbank.circuit_breakers import circuit_health  # noqa: PLC0415

    cb_status = circuit_health()
    if cb_status:
        rprint()
        rprint("[bold]Circuit breakers[/bold]")
        for provider, info in cb_status.items():
            state = info["state"]
            if state == "open":
                icon = "[red]✗[/red]"
                all_ok = False
            else:
                icon = "[green]✓[/green]"
            rprint(f"  {icon}  {provider:<32} {state}")

    rprint()
    if all_ok:
        rprint("[green bold]all systems nominal[/green bold]")
    else:
        rprint("[red bold]health check failed — see above for details[/red bold]")
        raise typer.Exit(code=1)


@app.command()
def init() -> None:
    """Initialise the _riverbank schema by running Alembic migrations.

    Also activates the built-in ``pg:skos-integrity`` shape bundle via
    ``pg_ripple.load_shape_bundle('skos-integrity')`` (pg-ripple ≥ 0.98.0).
    The six SKOS structural shapes are defined in pg-ripple; riverbank ships
    no Turtle files for them.
    """
    from alembic import command  # noqa: PLC0415
    from alembic.config import Config  # noqa: PLC0415

    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    rprint("[green]✓[/green]  schema migrations applied")

    # Activate the SKOS integrity shape bundle (pg-ripple ≥ 0.98.0)
    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.catalog.graph import load_shape_bundle  # noqa: PLC0415

    settings = get_settings()
    engine = create_engine(settings.db.dsn)
    try:
        with engine.connect() as conn:
            loaded = load_shape_bundle(conn, "skos-integrity")
            if loaded:
                rprint("[green]✓[/green]  pg:skos-integrity shape bundle activated")
            else:
                rprint(
                    "[yellow]![/yellow]  pg_ripple not available — "
                    "skos-integrity shape bundle skipped"
                )
    finally:
        engine.dispose()


@app.command()
def ingest(
    corpus: str = typer.Argument(..., help="Path to a corpus directory or file"),
    profile_name: str = typer.Option(
        "default", "--profile", "-p", help="Compiler profile name or YAML file path"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Parse and fragment only; skip extraction and graph writes"
    ),
    mode: str = typer.Option(
        "full",
        "--mode", "-m",
        help="Extraction mode: full | vocabulary",
    ),
    set_overrides: list[str] = typer.Option(
        [],
        "--set",
        help="Override a config key at runtime, e.g. --set llm.provider=ollama (repeatable)",
    ),
) -> None:
    """Ingest a document corpus into the knowledge graph.

    Discovers Markdown files under CORPUS, fragments each file at heading
    boundaries, applies the editorial policy gate, extracts triples (using
    the extractor declared in the profile), and writes them to pg_ripple with
    confidence scores and provenance edges.

    Unchanged fragments (same xxh3_128 hash) are skipped automatically —
    re-ingesting an unchanged corpus produces zero LLM calls.

    Use ``--mode vocabulary`` to run the vocabulary pass only (extracts
    ``skos:Concept`` triples into the ``<vocab>`` named graph).  The profile
    field ``run_mode_sequence: ['vocabulary', 'full']`` runs both passes
    automatically.
    """
    from pathlib import Path  # noqa: PLC0415

    from riverbank.pipeline import CompilerProfile, IngestPipeline  # noqa: PLC0415

    # Resolve the profile
    profile_path = Path(profile_name)
    if profile_path.exists() and profile_path.suffix in {".yaml", ".yml"}:
        profile = CompilerProfile.from_yaml(profile_path)
    else:
        profile = CompilerProfile(name=profile_name)

    pipeline = IngestPipeline(set_overrides=set_overrides)

    rprint(f"[bold]riverbank ingest[/bold]  corpus={corpus!r}  profile={profile.name!r}")
    if dry_run:
        rprint("[dim]dry-run mode — extraction and graph writes are skipped[/dim]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        transient=True,
    ) as progress:
        task = progress.add_task("Ingesting…", total=None)
        _counts: dict[str, int] = {"processed": 0, "skipped": 0, "errors": 0}

        def _on_progress(event: str, data: dict) -> None:
            if event == "corpus_analysis_start":
                n = data.get("n_docs", "?")
                progress.update(task, description=f"[magenta]corpus analysis[/magenta] ({n} docs)")
            elif event == "corpus_analysis_done":
                n = data.get("n_clusters", "?")
                progress.update(task, description=f"[magenta]clustered → {n} clusters[/magenta]")
            elif event == "preprocessing_start":
                name = data["source"].rsplit("/", 1)[-1]
                progress.update(task, description=f"[magenta]preprocessing[/magenta] {name}")
            elif event == "preprocessing_done":
                pass  # source_start follows immediately
            elif event == "source_start":
                name = data["source"].rsplit("/", 1)[-1]
                n = data["total_fragments"]
                progress.update(task, description=f"[cyan]{name}[/cyan] ({n} fragments)")
            elif event == "fragment":
                status = data["status"]
                if status == "processing":
                    _counts["processed"] += 1
                    key = data["key"]
                    progress.update(
                        task,
                        advance=1,
                        description=f"[cyan]{key}[/cyan]",
                    )
                else:
                    _counts["skipped"] += 1
                    progress.advance(task)

        stats = pipeline.run(
            corpus_path=corpus,
            profile=profile,
            dry_run=dry_run,
            mode=mode,
            progress_callback=_on_progress,
        )

    table = Table(
        title="Ingest summary",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Metric")
    table.add_column("Value", justify="right")

    table.add_row("Fragments processed", str(stats["fragments_processed"]))
    table.add_row("Fragments skipped (hash)", str(stats["fragments_skipped_hash"]))
    gate_skipped = stats["fragments_skipped"] - stats["fragments_skipped_hash"]
    table.add_row("Fragments skipped (gate)", str(gate_skipped))
    table.add_row("Triples written", str(stats["triples_written"]))
    table.add_row("LLM calls", str(stats["llm_calls"]))
    table.add_row("Prompt tokens", str(stats["prompt_tokens"]))
    table.add_row("Completion tokens", str(stats["completion_tokens"]))
    if stats.get("preprocessing_calls", 0) > 0:
        table.add_row("Preprocessing calls", str(stats["preprocessing_calls"]))
        table.add_row("Preprocessing prompt tokens", str(stats.get("preprocessing_prompt_tokens", 0)))
        table.add_row("Preprocessing completion tokens", str(stats.get("preprocessing_completion_tokens", 0)))
    table.add_row("Estimated cost (USD)", f"{stats['cost_usd']:.6f}")
    table.add_row("Errors", str(stats["errors"]))

    rprint(table)

    if stats["errors"] > 0:
        rprint(f"[red bold]{stats['errors']} error(s) — see logs for details[/red bold]")
        raise typer.Exit(code=1)

    rprint("[green bold]ingest complete[/green bold]")


@app.command("clear-graph")
def clear_graph(
    graph: str | None = typer.Option(
        None,
        "--graph",
        "-g",
        help="Named graph IRI to clear (e.g. http://riverbank.example/graph/trusted). Omit to clear ALL graphs.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Delete all triples from a named graph (or every graph)."""
    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.catalog.graph import clear_graph as _clear_graph  # noqa: PLC0415

    target = f"<{graph}>" if graph else "ALL graphs"
    if not yes:
        typer.confirm(f"Delete all triples from {target}?", abort=True)

    settings = get_settings()
    engine = create_engine(settings.db.dsn)
    try:
        with engine.connect() as conn:
            deleted = _clear_graph(conn, named_graph=graph)
            conn.commit()
    finally:
        engine.dispose()

    rprint(f"[green bold]clear-graph complete[/green bold]  graph={target}  deleted≈{deleted}")


@app.command()
def query(
    sparql: str = typer.Argument(..., help="SPARQL SELECT or ASK query string"),
    named_graph: str | None = typer.Option(
        None, "--graph", "-g", help="Restrict query to this named graph IRI"
    ),
    output_format: str = typer.Option(
        "table", "--format", "-f", help="Output format: table | json | csv"
    ),
    expand: str | None = typer.Option(
        None, "--expand", "-e",
        help="Comma-separated seed terms to expand via the <thesaurus> named graph before querying",
    ),
    include_tentative: bool = typer.Option(
        False, "--include-tentative",
        help="Union trusted + tentative graphs; results ordered by confidence descending",
    ),
) -> None:
    """Execute a SPARQL SELECT or ASK query against the compiled knowledge graph.

    Routes the query through pg_ripple.sparql().  Falls back with a
    warning when pg_ripple is not installed.

    With ``--expand term1,term2`` the terms are looked up in the
    ``<thesaurus>`` named graph (``skos:altLabel``, ``skos:related``,
    ``skos:exactMatch``, ``skos:closeMatch``) and the expanded synonym set is
    logged before the query is dispatched.

    With ``--include-tentative`` the trusted and tentative graphs are unioned
    and results are ordered by confidence descending.  Use this for discovery.
    """
    import json as _json  # noqa: PLC0415

    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.catalog.graph import sparql_query, sparql_query_with_thesaurus  # noqa: PLC0415

    settings = get_settings()
    engine = create_engine(settings.db.dsn)
    try:
        with engine.connect() as conn:
            if include_tentative:
                # v0.12.0 two-tier query model: union trusted + tentative graphs.
                # Wrap the user query in a UNION across both named graphs and
                # order by confidence descending.
                tentative_graph = "http://riverbank.example/graph/tentative"
                tentative_query = (
                    f"SELECT * WHERE {{ "
                    f"{{ GRAPH <{tentative_graph}> {{ {sparql.strip().rstrip(';')} }} }} "
                    f"}} ORDER BY DESC(?confidence) LIMIT 500"
                    if "SELECT" in sparql.upper()
                    else sparql
                )
                trusted_rows = sparql_query(conn, sparql, named_graph=named_graph)
                try:
                    tentative_rows = sparql_query(conn, tentative_query, named_graph=None)
                except Exception:  # noqa: BLE001
                    tentative_rows = []
                rows = trusted_rows + tentative_rows
            elif expand:
                seed_terms = [t.strip() for t in expand.split(",") if t.strip()]
                rows = sparql_query_with_thesaurus(
                    conn, sparql, named_graph=named_graph, expand_terms=seed_terms
                )
            else:
                rows = sparql_query(conn, sparql, named_graph=named_graph)
    finally:
        engine.dispose()

    if not rows:
        rprint("[dim]No results.[/dim]")
        return

    if output_format == "json":
        rprint(_json.dumps(rows, default=str, indent=2))
        return

    if output_format == "csv":
        import csv  # noqa: PLC0415
        import sys  # noqa: PLC0415

        writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        return

    # Default: rich table
    title = "SPARQL results (trusted + tentative)" if include_tentative else "SPARQL results"
    table = Table(title=title, show_header=True, header_style="bold cyan")
    for col in rows[0]:
        table.add_column(str(col))
    for row in rows:
        table.add_row(*[str(v) for v in row.values()])
    rprint(table)


@app.command()
def runs(
    since: str = typer.Option(
        "24h", "--since", "-s", help="Show runs since this duration (e.g. 1h, 30m, 7d)"
    ),
    profile: str | None = typer.Option(
        None, "--profile", "-p", help="Filter by profile name"
    ),
    limit: int = typer.Option(50, "--limit", "-n", help="Maximum rows to return"),
) -> None:
    """Inspect recent compiler runs with outcome, token counts, and Langfuse links.

    Shows one row per run with: source IRI, fragment key, profile, outcome,
    prompt/completion tokens, cost (USD), and Langfuse trace deep-link.
    """
    import re  # noqa: PLC0415
    from datetime import timedelta  # noqa: PLC0415

    from sqlalchemy import create_engine, text  # noqa: PLC0415

    from riverbank.cost_tables import format_cost  # noqa: PLC0415

    # Parse the --since duration
    match = re.fullmatch(r"(\d+)(h|m|d|s)", since.strip().lower())
    if not match:
        rprint(f"[red]Invalid --since value: {since!r}  (expected e.g. 1h, 30m, 7d)[/red]")
        raise typer.Exit(code=1)
    amount, unit = int(match.group(1)), match.group(2)
    delta = {"h": timedelta(hours=amount), "m": timedelta(minutes=amount),
             "d": timedelta(days=amount), "s": timedelta(seconds=amount)}[unit]

    settings = get_settings()
    langfuse_host = settings.langfuse.host

    sql = text(
        "SELECT r.id, s.iri, f.fragment_key, p.name AS profile_name, "
        "       r.outcome, r.prompt_tokens, r.completion_tokens, "
        "       r.cost_usd, r.langfuse_trace_id, r.started_at "
        "FROM _riverbank.runs r "
        "JOIN _riverbank.fragments f ON f.id = r.fragment_id "
        "JOIN _riverbank.sources s  ON s.id = f.source_id "
        "JOIN _riverbank.profiles p ON p.id = r.profile_id "
        "WHERE r.started_at >= now() - :delta "
        + ("AND p.name = :profile " if profile else "")
        + "ORDER BY r.started_at DESC "
        "LIMIT :limit"
    )
    params: dict = {"delta": delta, "limit": limit}
    if profile:
        params["profile"] = profile

    engine = create_engine(settings.db.dsn)
    try:
        with engine.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
    except Exception as exc:  # noqa: BLE001
        rprint(f"[red]Could not query runs: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()

    if not rows:
        rprint(f"[dim]No runs found in the last {since}.[/dim]")
        return

    table = Table(
        title=f"Runs — last {since}",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("ID", no_wrap=True)
    table.add_column("Source")
    table.add_column("Fragment key")
    table.add_column("Profile")
    table.add_column("Outcome")
    table.add_column("Prompt tok", justify="right")
    table.add_column("Compl tok", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("Langfuse")

    for row in rows:
        outcome_fmt = (
            "[green]success[/green]" if row.outcome == "success"
            else f"[red]{row.outcome}[/red]"
        )
        trace_link = (
            f"{langfuse_host}/trace/{row.langfuse_trace_id}"
            if row.langfuse_trace_id else "[dim]—[/dim]"
        )
        table.add_row(
            str(row.id),
            row.iri,
            row.fragment_key,
            row.profile_name,
            outcome_fmt,
            str(row.prompt_tokens or 0),
            str(row.completion_tokens or 0),
            format_cost(float(row.cost_usd or 0)),
            trace_link,
        )

    rprint(table)


# ---------------------------------------------------------------------------
# profile sub-app
# ---------------------------------------------------------------------------

profile_app = typer.Typer(name="profile", help="Manage compiler profiles.", no_args_is_help=True)
app.add_typer(profile_app)


@profile_app.command("register")
def profile_register(
    yaml_path: str = typer.Argument(..., help="Path to the profile YAML file"),
) -> None:
    """Register a compiler profile from a YAML file into the catalog.

    The profile is upserted by (name, version).  If the same name+version
    already exists the existing row is left unchanged.
    """
    from pathlib import Path  # noqa: PLC0415

    from riverbank.pipeline import CompilerProfile, IngestPipeline  # noqa: PLC0415

    path = Path(yaml_path)
    if not path.exists():
        rprint(f"[red]Profile file not found: {yaml_path}[/red]")
        raise typer.Exit(code=1)

    profile = CompilerProfile.from_yaml(path)
    pipeline = IngestPipeline()

    from sqlalchemy import create_engine  # noqa: PLC0415

    engine = create_engine(pipeline._settings.db.dsn)
    try:
        with engine.connect() as conn:
            db_id = pipeline._ensure_profile(conn, profile)
    finally:
        engine.dispose()

    rprint(
        f"[green]✓[/green]  profile [bold]{profile.name}[/bold] v{profile.version} "
        f"registered (id={db_id})"
    )


# ---------------------------------------------------------------------------
# source sub-app
# ---------------------------------------------------------------------------

source_app = typer.Typer(name="source", help="Manage registered sources.", no_args_is_help=True)
app.add_typer(source_app)


@source_app.command("set-profile")
def source_set_profile(
    source_iri: str = typer.Argument(..., help="Source IRI to update"),
    profile_name: str = typer.Argument(..., help="Profile name to associate"),
    profile_version: int = typer.Option(
        1, "--version", "-v", help="Profile version"
    ),
) -> None:
    """Associate a registered source with a compiler profile.

    Updates the ``profile_id`` column in ``_riverbank.sources`` for the given
    source IRI.  The profile must already be registered (use
    ``riverbank profile register``).
    """
    from sqlalchemy import create_engine, text  # noqa: PLC0415

    settings = get_settings()
    engine = create_engine(settings.db.dsn)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id FROM _riverbank.profiles "
                    "WHERE name = :name AND version = :version"
                ),
                {"name": profile_name, "version": profile_version},
            ).fetchone()
            if row is None:
                rprint(
                    f"[red]Profile '{profile_name}' v{profile_version} not found — "
                    f"run 'riverbank profile register' first.[/red]"
                )
                raise typer.Exit(code=1)
            profile_id = row[0]

            result = conn.execute(
                text(
                    "UPDATE _riverbank.sources SET profile_id = :pid WHERE iri = :iri"
                ),
                {"pid": profile_id, "iri": source_iri},
            )
            conn.commit()

            if result.rowcount == 0:
                rprint(f"[yellow]Source IRI not found in catalog: {source_iri}[/yellow]")
                raise typer.Exit(code=1)

    finally:
        engine.dispose()

    rprint(
        f"[green]✓[/green]  source [bold]{source_iri}[/bold] assigned to "
        f"profile [bold]{profile_name}[/bold] v{profile_version}"
    )


@app.command()
def lint(
    named_graph: str = typer.Option(
        "http://riverbank.example/graph/trusted",
        "--graph", "-g",
        help="Named graph IRI to validate",
    ),
    shacl_only: bool = typer.Option(
        False, "--shacl-only",
        help="Run SHACL quality report only (no other lint checks)",
    ),
    threshold: float = typer.Option(
        0.7, "--threshold", "-t",
        help="Minimum acceptable SHACL score [0.0–1.0]",
    ),
    layer: str = typer.Option(
        "", "--layer", "-l",
        help="Lint layer: '' (default SHACL) | 'vocab' (SKOS integrity on <vocab> graph)",
    ),
) -> None:
    """Run a SHACL quality report against a named graph.

    With ``--shacl-only`` (the standard v0.3.0 invocation) this is a thin
    wrapper around ``pg_ripple.shacl_score()``.  Exits non-zero if the score
    falls below the profile threshold.

    With ``--layer vocab`` this runs the ``pg:skos-integrity`` shape bundle
    against the ``<vocab>`` named graph and reports any violations.

    Example::

        riverbank lint --shacl-only --graph http://riverbank.example/graph/trusted
        riverbank lint --layer vocab
    """
    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.catalog.graph import run_shape_bundle, shacl_score  # noqa: PLC0415

    if layer == "vocab":
        # SKOS integrity shape bundle against the <vocab> named graph
        vocab_graph = named_graph if named_graph != "http://riverbank.example/graph/trusted" \
            else "http://riverbank.example/graph/vocab"
        settings = get_settings()
        engine = create_engine(settings.db.dsn)
        try:
            with engine.connect() as conn:
                results = run_shape_bundle(conn, "skos-integrity", vocab_graph)
        finally:
            engine.dispose()

        rprint(
            f"[bold]riverbank lint --layer vocab[/bold]  graph={vocab_graph!r}\n"
        )
        if not results:
            rprint("[green bold]SKOS integrity: no violations (or pg_ripple not available)[/green bold]")
            return

        from rich.table import Table as RichTable  # noqa: PLC0415

        tbl = RichTable(title="SKOS integrity violations", show_header=True, header_style="bold red")
        for col in results[0]:
            tbl.add_column(str(col))
        for row in results:
            tbl.add_row(*[str(v) for v in row.values()])
        rprint(tbl)
        raise typer.Exit(code=1)

    if not shacl_only:
        # v0.6.0: full lint pass — SHACL + SKOS integrity + pgc:LintFinding triples
        settings = get_settings()
        engine = create_engine(settings.db.dsn)
        try:
            with engine.connect() as conn:
                from riverbank.observability import run_full_lint  # noqa: PLC0415

                summary = run_full_lint(conn, named_graph, threshold=threshold)
                conn.commit()
        finally:
            engine.dispose()

        color = "green" if summary["passed"] else "red"
        rprint(
            f"[bold]riverbank lint[/bold]  graph={named_graph!r}\n\n"
            f"  SHACL score: [{color}]{summary['shacl_score']:.4f}[/{color}]  "
            f"(threshold {threshold:.2f})\n"
            f"  Findings: {summary['finding_count']}"
        )

        if summary["findings"]:
            from rich.table import Table as RichTable  # noqa: PLC0415

            tbl = RichTable(
                title="Lint findings",
                show_header=True,
                header_style="bold red",
            )
            tbl.add_column("Subject")
            tbl.add_column("Type")
            tbl.add_column("Message")
            tbl.add_column("Severity")
            for f in summary["findings"]:
                tbl.add_row(
                    f["subject_iri"], f["finding_type"], f["message"], f["severity"]
                )
            rprint(tbl)

        if not summary["passed"]:
            rprint("\n[red bold]Lint FAILED[/red bold]")
            raise typer.Exit(code=1)

        rprint("\n[green bold]Lint passed[/green bold]")
        return

    settings = get_settings()
    engine = create_engine(settings.db.dsn)
    try:
        with engine.connect() as conn:
            score = shacl_score(conn, named_graph)
    finally:
        engine.dispose()

    color = "green" if score >= threshold else "red"
    rprint(
        f"[bold]riverbank lint[/bold]  graph={named_graph!r}\n\n"
        f"  SHACL score: [{color}]{score:.4f}[/{color}]  "
        f"(threshold {threshold:.2f})"
    )

    if score < threshold:
        rprint(
            f"\n[red bold]SHACL quality gate FAILED — "
            f"score {score:.4f} < threshold {threshold:.2f}[/red bold]"
        )
        raise typer.Exit(code=1)

    rprint("\n[green bold]SHACL quality gate passed[/green bold]")


@app.command()
def explain(
    artifact_iri: str = typer.Argument(..., help="IRI of the compiled artifact to inspect"),
) -> None:
    """Dump the dependency tree of a compiled artifact.

    Shows which fragments, profile version, and rule set contributed to the
    named artifact.  The artifact IRI is typically the subject of a triple in
    the knowledge graph (e.g. ``entity:Acme``).

    Example::

        riverbank explain entity:Acme
    """
    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.catalog.graph import get_artifact_deps, suggest_sameas  # noqa: PLC0415

    settings = get_settings()
    engine = create_engine(settings.db.dsn)
    try:
        with engine.connect() as conn:
            deps = get_artifact_deps(conn, artifact_iri)
            # v0.5.0: fuzzy match suggestions from pg_ripple
            sameas_candidates = suggest_sameas(conn, artifact_iri)
    except Exception as exc:  # noqa: BLE001
        rprint(f"[red]Could not query artifact deps: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()

    rprint(f"[bold]riverbank explain[/bold]  artifact={artifact_iri!r}\n")

    if not deps:
        rprint(f"[dim]No dependency records found for {artifact_iri!r}.[/dim]")
        rprint(
            "[dim]Run 'riverbank ingest' first or check that the IRI is correct.[/dim]"
        )
    else:
        table = Table(title="Dependency tree", show_header=True, header_style="bold cyan")
        table.add_column("Dependency kind")
        table.add_column("Reference")

        for dep in deps:
            table.add_row(dep["dep_kind"], dep["dep_ref"])

        rprint(table)

    # v0.5.0: show fuzzy match / sameAs suggestions when available
    if sameas_candidates:
        rprint("\n[bold]Fuzzy match suggestions (owl:sameAs candidates)[/bold]")
        for candidate in sameas_candidates:
            rprint(f"  [cyan]→[/cyan]  {candidate}")


@app.command("explain-rejections")
def explain_rejections(
    profile: str | None = typer.Option(
        None, "--profile", "-p", help="Filter by profile name"
    ),
    since: str = typer.Option(
        "1h", "--since", "-s", help="Show rejections from the last duration (e.g. 1h, 30m, 7d)"
    ),
    limit: int = typer.Option(
        100, "--limit", "-n", help="Maximum rejections to display"
    ),
) -> None:
    """Show triples discarded in recent extraction runs, grouped by rejection reason.

    Reports triples that were silently discarded during extraction — evidence
    span not found, confidence below noise floor, ontology mismatch, or safety
    cap.  Use this to diagnose which implied facts the pipeline is losing and
    to improve your extraction profile.

    Example::

        riverbank explain-rejections --profile docs-policy-v1 --since 1h
    """
    import re  # noqa: PLC0415
    from datetime import timedelta  # noqa: PLC0415

    from sqlalchemy import create_engine, text  # noqa: PLC0415

    # Parse the --since duration
    match = re.fullmatch(r"(\d+)(h|m|d|s)", since.strip().lower())
    if not match:
        rprint("[red]Invalid --since value. Use e.g. 1h, 30m, 7d[/red]")
        raise typer.Exit(code=1)
    amount, unit = int(match.group(1)), match.group(2)
    delta = {
        "h": timedelta(hours=amount),
        "m": timedelta(minutes=amount),
        "d": timedelta(days=amount),
        "s": timedelta(seconds=amount),
    }[unit]

    settings = get_settings()
    engine = create_engine(settings.db.dsn)
    try:
        with engine.connect() as conn:
            sql = text(
                "SELECT r.fragment_key, r.source_iri, r.profile_name, r.run_at, "
                "       r.diagnostics "
                "FROM _riverbank.runs r "
                "WHERE r.run_at >= now() - :delta "
                + ("AND r.profile_name = :profile " if profile else "")
                + "ORDER BY r.run_at DESC LIMIT :limit"
            )
            params: dict = {"delta": delta, "limit": limit}
            if profile:
                params["profile"] = profile
            rows = conn.execute(sql, params).fetchall()
    except Exception as exc:  # noqa: BLE001
        rprint(f"[red]Could not query runs: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()

    if not rows:
        rprint("[dim]No runs found in the specified time window.[/dim]")
        return

    import json as _json  # noqa: PLC0415

    rejection_counts: dict[str, int] = {
        "evidence_not_found": 0,
        "below_noise_floor": 0,
        "ontology_mismatch": 0,
        "safety_cap": 0,
        "invalid_triple": 0,
    }
    total_discarded = 0
    total_rejected_ontology = 0
    total_capped = 0

    for row in rows:
        diag = row[4]
        if isinstance(diag, str):
            try:
                diag = _json.loads(diag)
            except Exception:  # noqa: BLE001
                diag = {}
        if not isinstance(diag, dict):
            diag = {}
        total_discarded += diag.get("triples_discarded", 0)
        total_rejected_ontology += diag.get("triples_rejected_ontology", 0)
        total_capped += diag.get("triples_capped", 0)
        rejection_counts["below_noise_floor"] += diag.get("triples_discarded", 0)
        rejection_counts["ontology_mismatch"] += diag.get("triples_rejected_ontology", 0)
        rejection_counts["safety_cap"] += diag.get("triples_capped", 0)

    rprint(
        f"[bold]riverbank explain-rejections[/bold]  "
        f"since={since!r}  "
        f"{'profile=' + repr(profile) + '  ' if profile else ''}"
        f"runs_scanned={len(rows)}\n"
    )

    table = Table(
        title="Rejection summary",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Rejection reason")
    table.add_column("Count", justify="right")
    table.add_column("Description")

    reasons = [
        ("below_noise_floor", rejection_counts["below_noise_floor"],
         "confidence < 0.35 — triple below minimum threshold"),
        ("ontology_mismatch", rejection_counts["ontology_mismatch"],
         "predicate not in allowed_predicates allowlist"),
        ("safety_cap", rejection_counts["safety_cap"],
         "fragment exceeded max_triples_per_fragment limit"),
        ("evidence_not_found", rejection_counts["evidence_not_found"],
         "excerpt not found verbatim in source text"),
        ("invalid_triple", rejection_counts["invalid_triple"],
         "Pydantic validation error in triple schema"),
    ]

    for reason, count, desc in reasons:
        color = "red" if count > 0 else "dim"
        table.add_row(
            f"[{color}]{reason}[/{color}]",
            f"[{color}]{count}[/{color}]",
            f"[dim]{desc}[/dim]",
        )

    rprint(table)

    if total_discarded + total_rejected_ontology + total_capped == 0:
        rprint(
            "\n[green]No rejections recorded in this window. "
            "Run riverbank ingest first to populate rejection stats.[/green]"
        )
    else:
        rprint(
            f"\n[dim]Tip: review your profile's allowed_predicates allowlist "
            f"and extraction_strategy.max_triples_per_fragment to tune the "
            f"rejection rates.[/dim]"
        )


@app.command("promote-tentative")
def promote_tentative(
    tentative_graph: str = typer.Option(
        "http://riverbank.example/graph/tentative",
        "--tentative-graph", "-t",
        help="IRI of the tentative named graph to read from",
    ),
    trusted_graph: str = typer.Option(
        "http://riverbank.example/graph/trusted",
        "--trusted-graph", "-g",
        help="IRI of the trusted named graph to promote into",
    ),
    threshold: float = typer.Option(
        0.75, "--threshold",
        help="Consolidated confidence threshold for promotion (0.0–1.0)",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Show triples that would be promoted without modifying the graph",
    ),
    limit: int = typer.Option(
        500, "--limit", "-n",
        help="Maximum tentative triples to consider per run",
    ),
) -> None:
    """Promote tentative triples whose consolidated confidence crosses the trusted threshold.

    Reads all triples from the tentative graph and applies noisy-OR confidence
    consolidation with source diversity scoring.  Triples whose consolidated
    confidence reaches --threshold are promoted to the trusted graph and a
    pgc:PromotionEvent provenance record is written.

    Promotion is NEVER automatic — always review with --dry-run first.

    Example::

        # Preview promotions
        riverbank promote-tentative --dry-run

        # Apply promotions
        riverbank promote-tentative
    """
    import json as _json  # noqa: PLC0415
    from datetime import datetime, timezone  # noqa: PLC0415

    from sqlalchemy import create_engine, text  # noqa: PLC0415

    from riverbank.catalog.graph import sparql_query  # noqa: PLC0415
    from riverbank.postprocessors.consolidate import NoisyORConsolidator  # noqa: PLC0415

    settings = get_settings()
    engine = create_engine(settings.db.dsn)

    # Step 1: Query tentative graph for all triples
    sparql_q = (
        f"SELECT ?s ?p ?o ?confidence ?source_iri ?fragment_key ?excerpt WHERE {{"
        f"  GRAPH <{tentative_graph}> {{"
        f"    ?s ?p ?o ."
        f"    OPTIONAL {{ ?s <http://riverbank.example/pgc/confidence> ?confidence . }}"
        f"    OPTIONAL {{ ?s <http://riverbank.example/pgc/sourceIri> ?source_iri . }}"
        f"    OPTIONAL {{ ?s <http://riverbank.example/pgc/fragmentKey> ?fragment_key . }}"
        f"    OPTIONAL {{ ?s <http://riverbank.example/pgc/excerpt> ?excerpt . }}"
        f"  }}"
        f"}} LIMIT {limit}"
    )

    try:
        with engine.connect() as conn:
            raw_rows = sparql_query(conn, sparql_q)
    except Exception as exc:  # noqa: BLE001
        rprint(f"[red]Could not query tentative graph: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()

    if not raw_rows:
        rprint(
            f"[dim]No triples found in tentative graph <{tentative_graph}>.[/dim]\n"
            "[dim]Run riverbank ingest with a permissive profile first.[/dim]"
        )
        return

    # Step 2: Build mock triple objects for the consolidator
    class _MockTriple:
        def __init__(self, row: dict) -> None:
            self.subject = str(row.get("s", ""))
            self.predicate = str(row.get("p", ""))
            self.object_value = str(row.get("o", ""))
            self.confidence = float(row.get("confidence", 0.5))
            self.fragment_key = str(row.get("fragment_key", ""))

            class _Ev:
                source_iri = str(row.get("source_iri", ""))
                excerpt = str(row.get("excerpt", ""))

            self.evidence = _Ev()

    mock_triples = [_MockTriple(r) for r in raw_rows]

    # Step 3: Consolidate with noisy-OR
    consolidator = NoisyORConsolidator(trusted_threshold=threshold)
    consolidated = consolidator.consolidate(mock_triples)
    candidates, _ = consolidator.split_by_threshold(consolidated)

    rprint(
        f"[bold]riverbank promote-tentative[/bold]  "
        f"tentative={tentative_graph!r}\n"
        f"  Total tentative triples:     {len(raw_rows)}\n"
        f"  After consolidation:         {len(consolidated)}\n"
        f"  Promotion candidates (≥{threshold:.2f}): {len(candidates)}\n"
    )

    if not candidates:
        rprint("[dim]No triples meet the confidence threshold for promotion.[/dim]")
        return

    # Show preview table
    table = Table(
        title="Promotion candidates" + (" (DRY RUN)" if dry_run else ""),
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Subject", max_width=40)
    table.add_column("Predicate", max_width=30)
    table.add_column("Object", max_width=40)
    table.add_column("Conf", justify="right")
    table.add_column("Diversity", justify="right")
    table.add_column("Sources", justify="right")

    for ct in candidates[:50]:  # show at most 50 in table
        table.add_row(
            ct.subject[:40],
            ct.predicate[:30],
            ct.object_value[:40],
            f"{ct.final_confidence:.3f}",
            str(ct.source_diversity),
            str(len(ct.provenance)),
        )

    rprint(table)

    if dry_run:
        rprint(
            f"\n[yellow bold]DRY RUN — {len(candidates)} triple(s) would be promoted. "
            f"Remove --dry-run to apply.[/yellow bold]"
        )
        return

    # Step 4: Write promoted triples to the trusted graph and record PromotionEvents
    engine2 = create_engine(settings.db.dsn)
    now_iso = datetime.now(timezone.utc).isoformat()
    promoted_count = 0

    try:
        with engine2.connect() as conn:
            from riverbank.catalog.graph import load_triples_with_confidence  # noqa: PLC0415
            from riverbank.prov import EvidenceSpan, ExtractedTriple  # noqa: PLC0415

            for ct in candidates:
                try:
                    # Build a minimal EvidenceSpan from the first provenance record
                    prov = ct.provenance[0] if ct.provenance else None
                    if prov is None or not prov.excerpt:
                        # Skip if no evidence — should not happen for well-formed tentative triples
                        continue
                    evidence = EvidenceSpan(
                        source_iri=prov.source_iri or "urn:promoted",
                        char_start=0,
                        char_end=max(1, len(prov.excerpt)),
                        excerpt=prov.excerpt or ct.subject[:50],
                    )
                    promoted_triple = ExtractedTriple(
                        subject=ct.subject,
                        predicate=ct.predicate,
                        object_value=ct.object_value,
                        confidence=ct.final_confidence,
                        evidence=evidence,
                        named_graph=trusted_graph,
                    )
                    written = load_triples_with_confidence(conn, [promoted_triple], trusted_graph)
                    if written > 0:
                        promoted_count += written
                        # Write pgc:PromotionEvent provenance record
                        _write_promotion_event(conn, ct, trusted_graph, now_iso)
                except Exception as _exc:  # noqa: BLE001
                    rprint(f"[yellow]Skipped triple ({ct.subject[:40]}…): {_exc}[/yellow]")

            conn.commit()
    except Exception as exc:  # noqa: BLE001
        rprint(f"[red]Promotion failed: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    finally:
        engine2.dispose()

    rprint(
        f"\n[green bold]Promoted {promoted_count} triple(s) to {trusted_graph!r}[/green bold]"
    )


def _write_promotion_event(conn: object, ct: object, trusted_graph: str, now_iso: str) -> None:
    """Write a pgc:PromotionEvent provenance record for a promoted triple."""
    try:
        import json as _json  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        subj = getattr(ct, "subject", "")
        pred = getattr(ct, "predicate", "")
        obj = getattr(ct, "object_value", "")
        conf = getattr(ct, "final_confidence", 0.0)
        diversity = getattr(ct, "source_diversity", 1)

        conn.execute(  # type: ignore[union-attr]
            text(
                "INSERT INTO _riverbank.log (event_type, payload, occurred_at) "
                "VALUES ('pgc:PromotionEvent', cast(:payload as jsonb), now())"
            ),
            {
                "payload": _json.dumps({
                    "triple": {"s": subj, "p": pred, "o": obj},
                    "final_confidence": conf,
                    "source_diversity": diversity,
                    "trusted_graph": trusted_graph,
                    "promoted_at": now_iso,
                })
            },
        )
    except Exception:  # noqa: BLE001
        pass  # PromotionEvent logging is best-effort


review_app = typer.Typer(
    name="review",
    help="Human review loop — Label Studio queue management.",
    no_args_is_help=True,
)
app.add_typer(review_app)


@review_app.command("queue")
def review_queue(
    named_graph: str = typer.Option(
        "http://riverbank.example/graph/trusted",
        "--graph", "-g",
        help="Named graph to scan for low-confidence extractions",
    ),
    limit: int = typer.Option(
        50, "--limit", "-n",
        help="Maximum number of items to add to the review queue",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Print candidate items without submitting to Label Studio",
    ),
    label_studio_url: str = typer.Option(
        "http://localhost:8080", "--ls-url",
        help="Label Studio URL",
    ),
    label_studio_key: str = typer.Option(
        "", "--ls-key",
        help="Label Studio API key",
    ),
    project_id: int = typer.Option(
        0, "--ls-project",
        help="Label Studio project ID (0 = auto-create)",
    ),
) -> None:
    """Run the active-learning review queue.

    Queries the knowledge graph for the *limit* extractions with the lowest
    confidence scores (centrality × uncertainty ranking), submits each as a
    Label Studio task, and refreshes task priorities.

    Use ``--dry-run`` to inspect candidates without touching Label Studio.

    Example::

        riverbank review queue --graph http://riverbank.example/graph/trusted --limit 20
    """
    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.catalog.graph import sparql_query  # noqa: PLC0415
    from riverbank.reviewers.label_studio import LabelStudioReviewer, ReviewTask  # noqa: PLC0415

    # SPARQL query: centrality × uncertainty ranking
    # Selects triples whose confidence is below 0.85, ordered lowest-first.
    queue_sparql = (
        "SELECT ?subject ?predicate ?object ?confidence ?fragment WHERE { "
        "  GRAPH <" + named_graph + "> { "
        "    ?subject ?predicate ?object . "
        "    ?subject <http://riverbank.example/ns/confidence> ?confidence . "
        "    OPTIONAL { ?subject <http://www.w3.org/ns/prov#wasDerivedFrom> ?fragment } "
        "    FILTER (?confidence < 0.85) "
        "  } "
        "} ORDER BY ?confidence LIMIT " + str(limit)
    )

    settings = get_settings()
    engine = create_engine(settings.db.dsn)
    try:
        with engine.connect() as conn:
            candidates = sparql_query(conn, queue_sparql, named_graph=named_graph)
    finally:
        engine.dispose()

    if not candidates:
        rprint("[dim]No low-confidence extractions found in review queue.[/dim]")
        return

    rprint(
        f"[bold]riverbank review queue[/bold]  graph={named_graph!r}  "
        f"candidates={len(candidates)}\n"
    )

    if dry_run:
        table = Table(
            title="Review queue candidates (dry-run)",
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Subject")
        table.add_column("Predicate")
        table.add_column("Object")
        table.add_column("Confidence", justify="right")
        for row in candidates:
            table.add_row(
                str(row.get("subject", "")),
                str(row.get("predicate", "")),
                str(row.get("object", "")),
                str(row.get("confidence", "")),
            )
        rprint(table)
        rprint("[dim]dry-run — no tasks submitted to Label Studio[/dim]")
        return

    reviewer = LabelStudioReviewer(
        url=label_studio_url,
        api_key=label_studio_key,
        project_id=project_id if project_id > 0 else None,
    )

    submitted = 0
    for row in candidates:
        task = ReviewTask(
            fragment_iri=str(row.get("fragment", "")),
            artifact_iri=str(row.get("subject", "")),
            subject=str(row.get("subject", "")),
            predicate=str(row.get("predicate", "")),
            object_value=str(row.get("object", "")),
            confidence=float(row.get("confidence", 0.0)),
            priority=1.0 - float(row.get("confidence", 0.5)),
        )
        task_id = reviewer.enqueue(task)
        if task_id is not None:
            submitted += 1

    rprint(
        f"[green]✓[/green]  {submitted}/{len(candidates)} tasks submitted to Label Studio"
    )


@app.command()
def recompile(
    profile: str = typer.Option(
        ..., "--profile", "-p",
        help="Profile name to recompile all sources for",
    ),
    version: int = typer.Option(
        1, "--version", "-v",
        help="Profile version",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Queue sources without re-extracting; print the semantic diff report only",
    ),
    limit: int = typer.Option(
        0, "--limit", "-n",
        help="Maximum sources to recompile (0 = all)",
    ),
) -> None:
    """Bulk reprocess all sources compiled by an older profile version.

    Queues all sources that were compiled by ``profile``/``version`` for
    recompilation, re-runs extraction, and produces a semantic diff report
    showing which triples were added, removed, or unchanged.

    Example::

        riverbank recompile --profile docs-policy-v1 --version 2
    """
    from sqlalchemy import create_engine, text  # noqa: PLC0415

    from riverbank.pipeline import CompilerProfile, IngestPipeline  # noqa: PLC0415

    settings = get_settings()
    engine = create_engine(settings.db.dsn)
    try:
        with engine.connect() as conn:
            # Find all sources associated with this profile version
            row = conn.execute(
                text(
                    "SELECT id FROM _riverbank.profiles "
                    "WHERE name = :name AND version = :version"
                ),
                {"name": profile, "version": version},
            ).fetchone()
            if row is None:
                rprint(
                    f"[red]Profile '{profile}' v{version} not found. "
                    "Register it first with 'riverbank profile register'.[/red]"
                )
                raise typer.Exit(code=1)
            profile_id = row[0]

            sql = text(
                "SELECT s.iri FROM _riverbank.sources s "
                "WHERE s.profile_id = :pid "
                "ORDER BY s.iri "
                + (f"LIMIT {limit}" if limit > 0 else "")
            )
            sources = [r[0] for r in conn.execute(sql, {"pid": profile_id}).fetchall()]
    finally:
        engine.dispose()

    if not sources:
        rprint(f"[dim]No sources found for profile '{profile}' v{version}.[/dim]")
        return

    rprint(
        f"[bold]riverbank recompile[/bold]  profile={profile!r}  version={version}  "
        f"sources={len(sources)}"
    )

    if dry_run:
        table = Table(title="Sources queued for recompilation (dry-run)",
                      show_header=True, header_style="bold cyan")
        table.add_column("Source IRI")
        for iri in sources:
            table.add_row(iri)
        rprint(table)
        rprint("[dim]dry-run — no recompilation performed[/dim]")
        return

    compiler_profile = CompilerProfile(name=profile, version=version)
    pipeline = IngestPipeline()

    total_stats: dict = {
        "sources_processed": 0,
        "fragments_processed": 0,
        "triples_written": 0,
        "errors": 0,
    }
    for iri in sources:
        try:
            stats = pipeline.run(corpus_path=iri, profile=compiler_profile, dry_run=False)
            total_stats["sources_processed"] += 1
            total_stats["fragments_processed"] += stats.get("fragments_processed", 0)
            total_stats["triples_written"] += stats.get("triples_written", 0)
            total_stats["errors"] += stats.get("errors", 0)
        except Exception as exc:  # noqa: BLE001
            rprint(f"[red]Error recompiling {iri}: {exc}[/red]")
            total_stats["errors"] += 1

    table = Table(title="Recompile summary", show_header=True, header_style="bold cyan")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Sources processed", str(total_stats["sources_processed"]))
    table.add_row("Fragments processed", str(total_stats["fragments_processed"]))
    table.add_row("Triples written", str(total_stats["triples_written"]))
    table.add_row("Errors", str(total_stats["errors"]))
    rprint(table)

    if total_stats["errors"] > 0:
        rprint(f"[red bold]{total_stats['errors']} error(s)[/red bold]")
        raise typer.Exit(code=1)
    rprint("[green bold]recompile complete[/green bold]")


@app.command("explain-conflict")
def explain_conflict(
    iri: str = typer.Argument(..., help="IRI of the entity or fact to explain conflicts for"),
    named_graph: str = typer.Option(
        "http://riverbank.example/graph/trusted",
        "--graph", "-g",
        help="Named graph IRI to search for contradictions",
    ),
) -> None:
    """Explain contradictions for an entity or fact.

    A CLI wrapper around ``pg_ripple.explain_contradiction()`` — the
    minimal-cause reasoning engine (SAT-style hitting-set over the inference
    dependency graph) lives in pg-ripple and requires no Python implementation
    in riverbank.

    Falls back gracefully when ``pg_ripple.explain_contradiction()`` is not
    yet available (deferred per roadmap mitigation policy).

    Example::

        riverbank explain-conflict entity:Acme
    """
    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.catalog.graph import explain_contradiction  # noqa: PLC0415

    settings = get_settings()
    engine = create_engine(settings.db.dsn)
    try:
        with engine.connect() as conn:
            result = explain_contradiction(conn, iri, named_graph=named_graph)
    except Exception as exc:  # noqa: BLE001
        rprint(f"[red]Could not run explain-conflict: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()

    rprint(f"[bold]riverbank explain-conflict[/bold]  iri={iri!r}\n")

    if not result:
        rprint(f"[dim]No contradictions found for {iri!r}.[/dim]")
        rprint("[dim](pg_ripple.explain_contradiction may be unavailable — check pg_ripple version)[/dim]")
        return

    table = Table(title="Contradiction explanation", show_header=True, header_style="bold red")
    table.add_column("Role")
    table.add_column("IRI / Value")

    for key, val in result.items():
        if isinstance(val, list):
            for item in val:
                table.add_row(key, str(item))
        else:
            table.add_row(key, str(val))

    rprint(table)


# ---------------------------------------------------------------------------
# tenant sub-app  (v0.9.0)
# ---------------------------------------------------------------------------

tenant_app = typer.Typer(
    name="tenant",
    help="Multi-tenant lifecycle management (RLS activation, create/suspend/delete).",
    no_args_is_help=True,
)
app.add_typer(tenant_app)


@tenant_app.command("activate-rls")
def tenant_activate_rls() -> None:
    """Enable Row-Level Security on all _riverbank catalog tables.

    Activates the ``tenant_id`` RLS policies scaffolded in v0.4.0 (migration
    0002).  Safe to call multiple times — idempotent.

    Example::

        riverbank tenant activate-rls
    """
    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.tenants import activate_rls_for_all_tables  # noqa: PLC0415

    settings = get_settings()
    engine = create_engine(settings.db.dsn)
    try:
        with engine.connect() as conn:
            results = activate_rls_for_all_tables(conn)
            conn.commit()
    finally:
        engine.dispose()

    for table, ok in results.items():
        icon = "[green]✓[/green]" if ok else "[yellow]![/yellow]"
        rprint(f"  {icon}  _riverbank.{table}")

    if all(results.values()):
        rprint("\n[green bold]RLS activated on all catalog tables[/green bold]")
    else:
        rprint("\n[yellow]Some tables could not be updated — check DB permissions[/yellow]")


@tenant_app.command("create")
def tenant_create(
    tenant_id: str = typer.Argument(..., help="Unique tenant slug (alphanumeric, hyphens, underscores)"),
    display_name: str = typer.Option("", "--name", "-n", help="Human-readable name"),
    label_studio_org: int = typer.Option(0, "--ls-org", help="Label Studio organisation ID"),
) -> None:
    """Create a new tenant.

    Example::

        riverbank tenant create acme --name "Acme Corp" --ls-org 42
    """
    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.tenants import Tenant, create_tenant  # noqa: PLC0415

    tenant = Tenant(
        tenant_id=tenant_id,
        display_name=display_name or tenant_id,
        label_studio_org_id=label_studio_org if label_studio_org > 0 else None,
    )

    settings = get_settings()
    engine = create_engine(settings.db.dsn)
    try:
        with engine.connect() as conn:
            ok = create_tenant(conn, tenant)
            conn.commit()
    finally:
        engine.dispose()

    if ok:
        rprint(f"[green]✓[/green]  tenant [bold]{tenant_id}[/bold] created")
    else:
        rprint(f"[red]Failed to create tenant {tenant_id}[/red]")
        raise typer.Exit(code=1)


@tenant_app.command("suspend")
def tenant_suspend(
    tenant_id: str = typer.Argument(..., help="Tenant slug to suspend"),
) -> None:
    """Suspend a tenant (all tenant-scoped operations will be blocked by RLS).

    Example::

        riverbank tenant suspend acme
    """
    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.tenants import suspend_tenant  # noqa: PLC0415

    settings = get_settings()
    engine = create_engine(settings.db.dsn)
    try:
        with engine.connect() as conn:
            ok = suspend_tenant(conn, tenant_id)
            conn.commit()
    finally:
        engine.dispose()

    if ok:
        rprint(f"[yellow]![/yellow]  tenant [bold]{tenant_id}[/bold] suspended")
    else:
        rprint(f"[red]Failed to suspend tenant {tenant_id}[/red]")
        raise typer.Exit(code=1)


@tenant_app.command("delete")
def tenant_delete(
    tenant_id: str = typer.Argument(..., help="Tenant slug to delete"),
    gdpr: bool = typer.Option(False, "--gdpr", help="GDPR erasure: also delete all tenant data rows"),
) -> None:
    """Delete a tenant (soft-delete by default; --gdpr erases all data rows).

    Example::

        riverbank tenant delete acme
        riverbank tenant delete acme --gdpr
    """
    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.tenants import delete_tenant  # noqa: PLC0415

    settings = get_settings()
    engine = create_engine(settings.db.dsn)
    try:
        with engine.connect() as conn:
            ok = delete_tenant(conn, tenant_id, gdpr_erasure=gdpr)
            conn.commit()
    finally:
        engine.dispose()

    label = "GDPR-erased" if gdpr else "soft-deleted"
    if ok:
        rprint(f"[green]✓[/green]  tenant [bold]{tenant_id}[/bold] {label}")
    else:
        rprint(f"[red]Failed to delete tenant {tenant_id}[/red]")
        raise typer.Exit(code=1)


@tenant_app.command("list")
def tenant_list() -> None:
    """List all registered tenants.

    Example::

        riverbank tenant list
    """
    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.tenants import list_tenants  # noqa: PLC0415

    settings = get_settings()
    engine = create_engine(settings.db.dsn)
    try:
        with engine.connect() as conn:
            tenants = list_tenants(conn)
    finally:
        engine.dispose()

    if not tenants:
        rprint("[dim]No tenants registered.[/dim]")
        return

    table = Table(title="Tenants", show_header=True, header_style="bold cyan")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("LS Org")
    table.add_column("Graph prefix")

    for t in tenants:
        status_fmt = (
            "[green]active[/green]" if t.status.value == "active"
            else f"[yellow]{t.status.value}[/yellow]"
        )
        table.add_row(
            t.tenant_id,
            t.display_name,
            status_fmt,
            str(t.label_studio_org_id) if t.label_studio_org_id else "—",
            t.named_graph_prefix,
        )
    rprint(table)


# ---------------------------------------------------------------------------
# render command  (v0.9.0)
# ---------------------------------------------------------------------------

@app.command()
def render(
    entity_iri: str = typer.Argument(..., help="IRI of the entity or topic to render"),
    output_format: str = typer.Option(
        "markdown", "--format", "-f",
        help="Output format: markdown | jsonld | html",
    ),
    target_dir: str = typer.Option(
        "docs/", "--target", "-t",
        help="Directory to write rendered pages into",
    ),
    named_graph: str = typer.Option(
        "http://riverbank.example/graph/trusted",
        "--graph", "-g",
        help="Source named graph IRI",
    ),
    persist: bool = typer.Option(
        True, "--persist/--no-persist",
        help="Write pgc:RenderedPage artifact back to the graph",
    ),
) -> None:
    """Render an entity page from the compiled knowledge graph.

    Fetches all facts about ENTITY_IRI from the named graph and renders them
    as Markdown (Obsidian/MkDocs), JSON-LD, or HTML.  The output file is
    written to TARGET_DIR.

    Rendered pages are stored as ``pgc:RenderedPage`` artifacts with
    dependency edges to their source facts so that stale pages can be
    detected when facts change.

    Example::

        riverbank render http://example.org/entity/Acme --format markdown --target docs/
        riverbank render http://example.org/topic/HA --format jsonld
    """
    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.rendering import (  # noqa: PLC0415
        PageType,
        RenderFormat,
        RenderRequest,
        persist_rendered_page,
        render_page,
    )

    fmt_map = {
        "markdown": RenderFormat.MARKDOWN,
        "jsonld": RenderFormat.JSONLD,
        "html": RenderFormat.HTML,
    }
    fmt = fmt_map.get(output_format.lower())
    if fmt is None:
        rprint(f"[red]Unknown format: {output_format!r}. Use markdown, jsonld, or html.[/red]")
        raise typer.Exit(code=1)

    ext_map = {
        RenderFormat.MARKDOWN: ".md",
        RenderFormat.JSONLD: ".jsonld",
        RenderFormat.HTML: ".html",
    }
    from riverbank.rendering import _slug  # noqa: PLC0415

    output_path = f"{target_dir.rstrip('/')}/{_slug(entity_iri)}{ext_map[fmt]}"

    request = RenderRequest(
        entity_iri=entity_iri,
        fmt=fmt,
        named_graph=named_graph,
        output_path=output_path,
    )

    settings = get_settings()
    engine = create_engine(settings.db.dsn)
    try:
        with engine.connect() as conn:
            page = render_page(conn, request)
            if persist:
                persist_rendered_page(conn, page)
                conn.commit()
    except Exception as exc:  # noqa: BLE001
        rprint(f"[red]Render failed: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()

    rprint(
        f"[green]✓[/green]  rendered [bold]{entity_iri}[/bold] "
        f"→ [cyan]{output_path}[/cyan]  ({fmt.value})"
    )
    if persist:
        rprint(f"  pgc:RenderedPage  [dim]{page.page_iri}[/dim]")


# ---------------------------------------------------------------------------
# federation sub-app  (v0.9.0)
# ---------------------------------------------------------------------------

federation_app = typer.Typer(
    name="federation",
    help="Federated compilation — pull triples from remote pg_ripple instances.",
    no_args_is_help=True,
)
app.add_typer(federation_app)


@federation_app.command("register")
def federation_register(
    name: str = typer.Argument(..., help="Logical name for this endpoint"),
    sparql_url: str = typer.Argument(..., help="Remote SPARQL endpoint URL"),
    remote_graph: str = typer.Option(
        "http://riverbank.example/graph/trusted",
        "--remote-graph",
        help="Remote named graph IRI",
    ),
    weight: float = typer.Option(0.8, "--weight", "-w", help="Confidence weight [0.0–1.0]"),
    timeout: int = typer.Option(30, "--timeout", help="Query timeout in seconds"),
) -> None:
    """Register a remote pg_ripple SPARQL endpoint for federated compilation.

    Example::

        riverbank federation register peer-alpha https://peer.example.com/sparql
    """
    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.federation import FederationEndpoint, register_federation_endpoint  # noqa: PLC0415

    endpoint = FederationEndpoint(
        name=name,
        sparql_url=sparql_url,
        named_graph=remote_graph,
        confidence_weight=weight,
        timeout_seconds=timeout,
    )

    settings = get_settings()
    engine = create_engine(settings.db.dsn)
    try:
        with engine.connect() as conn:
            ok = register_federation_endpoint(conn, endpoint)
            conn.commit()
    finally:
        engine.dispose()

    if ok:
        rprint(f"[green]✓[/green]  endpoint [bold]{name}[/bold] registered → {sparql_url}")
    else:
        rprint(f"[red]Failed to register endpoint {name}[/red]")
        raise typer.Exit(code=1)


@federation_app.command("compile")
def federation_compile(
    name: str = typer.Argument(..., help="Name of the federation endpoint to pull from"),
    local_graph: str = typer.Option(
        "http://riverbank.example/graph/trusted",
        "--local-graph",
        help="Local named graph to write triples into",
    ),
    limit: int = typer.Option(1000, "--limit", "-n", help="Maximum triples to fetch"),
) -> None:
    """Pull triples from a remote pg_ripple endpoint and write them locally.

    Example::

        riverbank federation compile peer-alpha --limit 500
    """
    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.federation import (  # noqa: PLC0415
        federated_compile,
        list_federation_endpoints,
    )

    settings = get_settings()
    engine = create_engine(settings.db.dsn)
    try:
        with engine.connect() as conn:
            endpoints = list_federation_endpoints(conn)
            endpoint = next((e for e in endpoints if e.name == name), None)
            if endpoint is None:
                rprint(
                    f"[red]Endpoint '{name}' not found. "
                    "Register it first with 'riverbank federation register'.[/red]"
                )
                raise typer.Exit(code=1)

            result = federated_compile(conn, endpoint, local_named_graph=local_graph, limit=limit)
            if result.success:
                conn.commit()
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001
        rprint(f"[red]Federated compile failed: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()

    if result.success:
        rprint(
            f"[green]✓[/green]  federated compile from [bold]{name}[/bold]\n"
            f"  fetched: {result.triples_fetched}  written: {result.triples_written}"
        )
    else:
        rprint(f"[red]Federated compile failed: {result.error}[/red]")
        raise typer.Exit(code=1)


@review_app.command("collect")
def review_collect(
    profile_name: str = typer.Option(
        "default", "--profile", "-p",
        help="Profile name (used to resolve the example bank path)",
    ),
    label_studio_url: str = typer.Option(
        "http://localhost:8080", "--ls-url",
        help="Label Studio URL",
    ),
    label_studio_key: str = typer.Option(
        "", "--ls-key",
        help="Label Studio API key",
    ),
    project_id: int = typer.Option(
        0, "--ls-project",
        help="Label Studio project ID",
    ),
    write_to_graph: bool = typer.Option(
        True, "--write/--no-write",
        help="Write accepted/corrected decisions to the <human-review> named graph",
    ),
) -> None:
    """Collect completed review decisions from Label Studio.

    Fetches annotated tasks, writes corrections into the ``<human-review>``
    named graph, and exports each accepted/corrected decision to the profile's
    few-shot example bank.

    Example::

        riverbank review collect --profile docs-policy-v1
    """
    from pathlib import Path  # noqa: PLC0415

    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.example_bank import bank_path_for_profile, export_decision_to_bank  # noqa: PLC0415
    from riverbank.reviewers.label_studio import LabelStudioReviewer  # noqa: PLC0415

    reviewer = LabelStudioReviewer(
        url=label_studio_url,
        api_key=label_studio_key,
        project_id=project_id if project_id > 0 else None,
    )

    bank_path = bank_path_for_profile(profile_name)
    accepted = corrected = rejected = bank_size = 0

    settings = get_settings()
    engine = create_engine(settings.db.dsn)
    try:
        with engine.connect() as conn:
            for decision in reviewer.collect():
                if decision.accepted:
                    accepted += 1
                elif decision.corrected:
                    corrected += 1
                else:
                    rejected += 1

                if write_to_graph:
                    reviewer.write_decision_to_graph(conn, decision)

                new_size = export_decision_to_bank(decision, bank_path)
                if new_size:
                    bank_size = new_size

            if write_to_graph:
                conn.commit()
    finally:
        engine.dispose()

    rprint(
        f"[bold]riverbank review collect[/bold]  "
        f"accepted={accepted}  corrected={corrected}  rejected={rejected}\n"
        f"  example bank: {bank_path}  ({bank_size} entries)"
    )


# ---------------------------------------------------------------------------
# sbom command  (v0.10.0)
# ---------------------------------------------------------------------------

@app.command()
def sbom(
    output: str = typer.Option(
        "riverbank-sbom.json",
        "--output", "-o",
        help="Path to write the SBOM file",
    ),
    output_format: str = typer.Option(
        "json",
        "--format", "-f",
        help="Output format: json (default) | xml",
    ),
    no_audit: bool = typer.Option(
        False,
        "--no-audit",
        help="Skip the pip-audit CVE scan (produce SBOM only)",
    ),
) -> None:
    """Generate a CycloneDX SBOM for the installed riverbank package.

    Uses ``cyclonedx-py`` (installed via ``pip install riverbank[sbom]``) to
    produce a machine-readable Software Bill of Materials.  After generating
    the SBOM, ``pip-audit`` is run to check all dependencies for known CVEs;
    the command exits non-zero if any vulnerability is found.

    Output formats:

    * ``json`` (default) — CycloneDX JSON 1.6
    * ``xml`` — CycloneDX XML 1.6

    Example::

        riverbank sbom
        riverbank sbom --output sbom.xml --format xml
        riverbank sbom --no-audit
    """
    from pathlib import Path  # noqa: PLC0415

    from riverbank.sbom import SBOMResult, audit_vulnerabilities, generate_sbom  # noqa: PLC0415

    fmt = output_format.lower()
    if fmt not in {"json", "xml"}:
        rprint(f"[red]Unknown format: {output_format!r}. Use json or xml.[/red]")
        raise typer.Exit(code=1)

    output_path = Path(output)
    rprint(f"[bold]riverbank sbom[/bold]  format={fmt}  output={output_path}\n")

    rprint("[dim]Generating CycloneDX SBOM…[/dim]")
    result: SBOMResult = generate_sbom(output_path, fmt=fmt)  # type: ignore[arg-type]
    rprint(f"[green]✓[/green]  SBOM written to [cyan]{result.output_path}[/cyan]")

    if no_audit:
        rprint("[dim]CVE audit skipped (--no-audit)[/dim]")
        return

    rprint("[dim]Running pip-audit CVE scan…[/dim]")
    vulns = audit_vulnerabilities()
    result.vulnerabilities = vulns

    if not result.has_vulnerabilities:
        rprint("[green]✓[/green]  No known CVEs found in installed dependencies")
        return

    rprint(
        f"\n[red bold]pip-audit: {result.vulnerability_count} vulnerability(s) found![/red bold]"
    )
    vuln_table = Table(
        title="CVE findings",
        show_header=True,
        header_style="bold red",
    )
    vuln_table.add_column("Package")
    vuln_table.add_column("Version")
    vuln_table.add_column("CVE / Advisory")
    vuln_table.add_column("Fix versions")
    for v in result.vulnerabilities:
        vuln_table.add_row(
            v["name"],
            v["version"],
            v["id"],
            ", ".join(v["fix_versions"]) if v["fix_versions"] else "—",
        )
    rprint(vuln_table)
    raise typer.Exit(code=1)


@app.command("validate-graph")
def validate_graph(
    profile_name: str = typer.Option(
        "default", "--profile", "-p", help="Compiler profile name or YAML file path"
    ),
    named_graph: str | None = typer.Option(
        None, "--graph", "-g", help="Named graph IRI to validate against (defaults to profile named_graph)"
    ),
    fail_below: float = typer.Option(
        0.0, "--fail-below",
        help="Exit with code 1 if coverage fraction is below this threshold (0.0–1.0)",
    ),
) -> None:
    """Run the profile's competency questions against the compiled graph and report coverage.

    Reads the ``competency_questions`` list from the compiler profile (SPARQL ASK
    queries) and executes each one.  Prints a results table and a coverage score.

    Use ``--fail-below 1.0`` to fail CI unless all questions pass.
    """
    from pathlib import Path  # noqa: PLC0415

    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.catalog.graph import sparql_query  # noqa: PLC0415
    from riverbank.pipeline import CompilerProfile  # noqa: PLC0415

    # Resolve profile
    profile_path = Path(profile_name)
    if profile_path.exists() and profile_path.suffix in {".yaml", ".yml"}:
        profile = CompilerProfile.from_yaml(profile_path)
    else:
        profile = CompilerProfile(name=profile_name)

    cqs = profile.competency_questions
    if not cqs:
        rprint("[yellow]No competency_questions defined in the profile.[/yellow]")
        raise typer.Exit(code=0)

    graph = named_graph or profile.named_graph

    settings = get_settings()
    engine = create_engine(settings.db.dsn)

    table = Table(
        title=f"Competency question coverage — {profile.name} → {graph}",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Description")
    table.add_column("Result", justify="center")

    passed = 0
    failed_ids: list[str] = []

    try:
        with engine.connect() as conn:
            for cq in cqs:
                cq_id = cq.get("id", "?")
                description = cq.get("description", "")
                sparql = cq.get("sparql", "").strip()

                if not sparql:
                    table.add_row(cq_id, description, "[dim]—[/dim]")
                    continue

                # Execute ASK query
                try:
                    rows = sparql_query(conn, sparql, named_graph=graph)
                    # ASK returns {"result": True/False} or {"ASK": True/False}
                    ok = False
                    if rows:
                        row = rows[0]
                        ok = bool(row.get("result", row.get("ASK", row.get("ask", False))))
                except Exception as exc:  # noqa: BLE001
                    table.add_row(cq_id, description, f"[red]ERROR: {exc}[/red]")
                    failed_ids.append(cq_id)
                    continue

                if ok:
                    passed += 1
                    table.add_row(cq_id, description, "[green bold]PASS[/green bold]")
                else:
                    failed_ids.append(cq_id)
                    table.add_row(cq_id, description, "[red bold]FAIL[/red bold]")
    finally:
        engine.dispose()

    rprint(table)

    total = len(cqs)
    coverage = passed / total if total > 0 else 0.0
    coverage_pct = f"{coverage * 100:.0f}%"

    if failed_ids:
        rprint(f"\n[red]Failed:[/red] {', '.join(failed_ids)}")
    rprint(f"\n[bold]Coverage:[/bold] {passed}/{total} ({coverage_pct})")

    if coverage < fail_below:
        rprint(
            f"[red bold]Coverage {coverage_pct} is below threshold {fail_below * 100:.0f}% "
            f"— exiting with code 1[/red bold]"
        )
        raise typer.Exit(code=1)

    if not failed_ids:
        rprint("[green bold]All competency questions passed.[/green bold]")


@app.command("deduplicate-entities")
def deduplicate_entities(
    named_graph: str = typer.Option(
        "http://riverbank.example/graph/trusted",
        "--graph",
        "-g",
        help="Named graph IRI to deduplicate",
    ),
    threshold: float = typer.Option(
        0.92,
        "--threshold",
        "-t",
        help="Cosine-similarity threshold for merging entities (0.0–1.0)",
    ),
    model: str = typer.Option(
        "all-MiniLM-L6-v2",
        "--model",
        "-m",
        help="sentence-transformers model name for embedding entity labels",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Compute clusters but do not write owl:sameAs triples",
    ),
) -> None:
    """Post-1: Embed entity labels and write owl:sameAs links for duplicates.

    Queries the named graph for all unique entity IRIs, embeds their labels
    using sentence-transformers, clusters by cosine similarity, and promotes
    the shortest IRI in each cluster as canonical.  Alias IRIs are written
    back to the graph as ``owl:sameAs`` links.

    Use ``--dry-run`` to inspect clusters without modifying the graph.
    Requires sentence-transformers (``pip install 'riverbank[ingest]'``).
    """
    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.postprocessors.dedup import EntityDeduplicator  # noqa: PLC0415

    settings = get_settings()
    engine = create_engine(settings.db.dsn)

    deduplicator = EntityDeduplicator(model_name=model, threshold=threshold)

    rprint(
        f"[bold]riverbank deduplicate-entities[/bold]  "
        f"graph=<{named_graph}>  threshold={threshold}"
    )
    if dry_run:
        rprint("[dim]dry-run mode — owl:sameAs triples will NOT be written[/dim]")

    try:
        with engine.connect() as conn:
            result = deduplicator.deduplicate(conn, named_graph, dry_run=dry_run)
    finally:
        engine.dispose()

    table = Table(
        title="Entity deduplication summary",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Entities examined", str(result.entities_examined))
    table.add_row("Duplicate clusters found", str(result.clusters_found))
    table.add_row("owl:sameAs triples written", str(result.sameas_written))
    rprint(table)

    if result.clusters:
        cluster_table = Table(
            title="Duplicate clusters",
            show_header=True,
            header_style="bold magenta",
        )
        cluster_table.add_column("Canonical IRI")
        cluster_table.add_column("Aliases")
        cluster_table.add_column("Similarity", justify="right")
        for cluster in result.clusters:
            cluster_table.add_row(
                cluster.canonical,
                ", ".join(cluster.aliases),
                f"{cluster.similarity:.3f}",
            )
        rprint(cluster_table)

    if dry_run:
        rprint("[yellow]dry-run complete — no changes written[/yellow]")
    else:
        rprint("[green bold]deduplication complete[/green bold]")


@app.command("verify-triples")
def verify_triples(
    profile_name: str = typer.Option(
        "default", "--profile", "-p", help="Compiler profile name or YAML file path"
    ),
    named_graph: str | None = typer.Option(
        None,
        "--graph",
        "-g",
        help="Named graph IRI to verify (defaults to profile named_graph)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Compute verification outcomes but do not modify the graph",
    ),
) -> None:
    """Post-2: Re-evaluate low-confidence triples with a self-critique LLM call.

    Reads ``verification:`` config from the compiler profile.  For each triple
    below ``confidence_threshold``, asks the LLM whether the claim is supported
    by the stored evidence excerpt.  Confirmed triples with high verifier
    confidence are boosted; rejected triples are moved to the quarantine
    (``<draft>``) named graph for human review.

    Verification must be enabled in the profile::

        verification:
          enabled: true
          confidence_threshold: 0.75
          drop_below: 0.4
          boost_above: 0.8

    Use ``--dry-run`` to inspect outcomes without modifying the graph.
    Requires instructor + openai (``pip install 'riverbank[ingest]'``).
    """
    from pathlib import Path  # noqa: PLC0415

    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.pipeline import CompilerProfile  # noqa: PLC0415
    from riverbank.postprocessors.verify import VerificationPass  # noqa: PLC0415

    # Resolve profile
    profile_path = Path(profile_name)
    if profile_path.exists() and profile_path.suffix in {".yaml", ".yml"}:
        profile = CompilerProfile.from_yaml(profile_path)
    else:
        profile = CompilerProfile(name=profile_name)

    graph = named_graph or profile.named_graph

    verification_cfg: dict = getattr(profile, "verification", {})
    if not verification_cfg.get("enabled", False):
        rprint(
            "[yellow]verification is not enabled in this profile. "
            "Add 'verification: {enabled: true}' to enable.[/yellow]"
        )
        raise typer.Exit(code=0)

    settings = get_settings()
    engine = create_engine(settings.db.dsn)

    rprint(
        f"[bold]riverbank verify-triples[/bold]  "
        f"profile={profile.name!r}  graph=<{graph}>"
    )
    if dry_run:
        rprint("[dim]dry-run mode — no changes will be written[/dim]")

    verifier = VerificationPass(settings=settings)
    try:
        with engine.connect() as conn:
            result = verifier.verify(conn, graph, profile, dry_run=dry_run)
    finally:
        engine.dispose()

    table = Table(
        title="Verification pass summary",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Triples examined", str(result.triples_examined))
    table.add_row("Confidence boosted", str(result.boosted))
    table.add_row("Kept (unchanged)", str(result.kept))
    table.add_row("Quarantined (→ draft)", str(result.quarantined))
    table.add_row("Errors", str(result.errors))
    table.add_row("Prompt tokens", str(result.prompt_tokens))
    table.add_row("Completion tokens", str(result.completion_tokens))
    rprint(table)

    if result.errors > 0:
        rprint(f"[red]{result.errors} verification error(s) — see logs for details[/red]")

    if dry_run:
        rprint("[yellow]dry-run complete — no changes written[/yellow]")
    else:
        rprint("[green bold]verification pass complete[/green bold]")


# ---------------------------------------------------------------------------
# v0.13.0 — Entity Convergence commands
# ---------------------------------------------------------------------------


@app.command("normalize-predicates")
def normalize_predicates(
    named_graph: str = typer.Option(
        "http://riverbank.example/graph/trusted",
        "--graph", "-g",
        help="Named graph to normalize predicates in",
    ),
    threshold: float = typer.Option(
        0.88, "--threshold",
        help="Cosine-similarity threshold for predicate clustering (0.0–1.0)",
    ),
    rewrite: bool = typer.Option(
        False, "--rewrite",
        help="Rewrite existing triples to use canonical predicate IRIs (in addition to equivalentProperty)",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Show clusters without writing owl:equivalentProperty triples",
    ),
) -> None:
    """Cluster near-duplicate predicates and write owl:equivalentProperty links.

    Embeds predicate labels using sentence-transformers and clusters predicates
    by cosine similarity.  Within each cluster the most-frequent predicate is
    promoted as canonical; non-canonical predicates receive
    ``owl:equivalentProperty`` links.

    Use ``--rewrite`` to also rewrite existing triples to the canonical form.

    Example::

        riverbank normalize-predicates --graph http://riverbank.example/graph/trusted --dry-run
    """
    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.postprocessors.predicate_norm import PredicateNormalizer  # noqa: PLC0415

    settings = get_settings()
    engine = create_engine(settings.db.dsn)

    rprint(
        f"[bold]riverbank normalize-predicates[/bold]  "
        f"graph=<{named_graph}>  threshold={threshold}"
    )
    if dry_run:
        rprint("[dim]dry-run mode — no changes will be written[/dim]")

    normalizer = PredicateNormalizer(threshold=threshold, rewrite=rewrite)
    try:
        with engine.connect() as conn:
            result = normalizer.normalize(conn, named_graph, dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001
        rprint(f"[red]normalize-predicates failed: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()

    table = Table(
        title="Predicate normalization summary" + (" (DRY RUN)" if dry_run else ""),
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Predicates examined", str(result.predicates_examined))
    table.add_row("Clusters found", str(result.clusters_found))
    table.add_row("owl:equivalentProperty written", str(result.equivalent_property_written))
    if rewrite:
        table.add_row("Triples rewritten", str(result.triples_rewritten))
    rprint(table)

    if result.clusters_found > 0:
        cluster_table = Table(
            title="Predicate clusters",
            show_header=True,
            header_style="bold cyan",
        )
        cluster_table.add_column("Canonical", max_width=50)
        cluster_table.add_column("Aliases", max_width=60)
        cluster_table.add_column("Sim", justify="right")
        for cluster in result.clusters[:20]:
            cluster_table.add_row(
                cluster.canonical[:50],
                ", ".join(a[:25] for a in cluster.aliases[:3]),
                f"{cluster.similarity:.3f}",
            )
        rprint(cluster_table)

    if dry_run:
        rprint("\n[yellow]DRY RUN — no changes written[/yellow]")
    else:
        rprint(
            f"\n[green bold]Normalization complete. "
            f"{result.equivalent_property_written} owl:equivalentProperty triple(s) written.[/green bold]"
        )


# ---------------------------------------------------------------------------
# entities sub-app
# ---------------------------------------------------------------------------

entities_app = typer.Typer(
    name="entities",
    help="Entity registry management — list, merge, and inspect entity synonym rings.",
    no_args_is_help=True,
)
app.add_typer(entities_app)


@entities_app.command("list")
def entities_list(
    named_graph: str = typer.Option(
        "http://riverbank.example/graph/trusted",
        "--graph", "-g",
        help="Named graph to list entities from",
    ),
    limit: int = typer.Option(
        50, "--limit", "-n",
        help="Maximum number of entities to show",
    ),
) -> None:
    """List entities in the registry with their synonym rings.

    Displays all entity IRIs, labels, types, and known surface-form variants
    (``skos:altLabel`` synonym rings).

    Example::

        riverbank entities list --graph http://riverbank.example/graph/trusted
    """
    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.postprocessors.entity_linker import EntityLinker  # noqa: PLC0415

    settings = get_settings()
    engine = create_engine(settings.db.dsn)

    linker = EntityLinker()
    try:
        with engine.connect() as conn:
            registry = linker.load_registry(conn, named_graph, limit=limit)
    except Exception as exc:  # noqa: BLE001
        rprint(f"[red]entities list failed: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()

    if not registry.entities:
        rprint(f"[dim]No entities found in <{named_graph}>.[/dim]")
        return

    table = Table(
        title=f"Entity registry — <{named_graph}> ({len(registry.entities)} entities)",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("IRI", max_width=50)
    table.add_column("Label", max_width=30)
    table.add_column("Type", max_width=30)
    table.add_column("Variants", max_width=40)

    for entity in registry.entities[:limit]:
        table.add_row(
            entity.iri[:50],
            entity.label[:30],
            (entity.entity_type or "—")[:30],
            ", ".join(entity.variants[:3]) or "—",
        )

    rprint(table)


@entities_app.command("merge")
def entities_merge(
    entity: str = typer.Option(..., "--entity", help="IRI of the entity to merge FROM"),
    into: str = typer.Option(..., "--into", help="IRI of the canonical entity to merge INTO"),
    named_graph: str = typer.Option(
        "http://riverbank.example/graph/trusted",
        "--graph", "-g",
        help="Named graph to operate on",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Preview the merge without writing changes",
    ),
) -> None:
    """Merge one entity into another, writing a skos:altLabel for the alias.

    Rewrites all triples that reference the FROM entity to use the INTO entity
    IRI, and writes a ``skos:altLabel`` for the old label.

    Example::

        riverbank entities merge \\
            --entity ex:dataset \\
            --into ex:Dataset \\
            --graph http://riverbank.example/graph/trusted
    """
    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.postprocessors.entity_linker import EntityLinker  # noqa: PLC0415

    settings = get_settings()
    engine = create_engine(settings.db.dsn)

    linker = EntityLinker()
    try:
        with engine.connect() as conn:
            registry = linker.load_registry(conn, named_graph, limit=5000)
            merged = registry.merge(into_iri=into, from_iri=entity)
            if merged and not dry_run:
                # Write skos:altLabel for the merged entity's label
                from_record_label = entity.split("/")[-1].split("#")[-1]
                linker._write_alt_label(conn, named_graph, into, from_record_label)
                conn.commit()
    except Exception as exc:  # noqa: BLE001
        rprint(f"[red]entities merge failed: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()

    if not merged:
        rprint(f"[red]Merge failed — entity {entity!r} or {into!r} not found in registry[/red]")
        raise typer.Exit(code=1)

    if dry_run:
        rprint(
            f"[yellow]DRY RUN — would merge {entity!r} → {into!r}[/yellow]"
        )
    else:
        rprint(
            f"[green bold]Merged {entity!r} → {into!r}[/green bold]"
        )


# ---------------------------------------------------------------------------
# Contradiction detection
# ---------------------------------------------------------------------------


@app.command("detect-contradictions")
def detect_contradictions(
    profile_name: str = typer.Argument(
        ..., help="Profile name or path to YAML file"
    ),
    named_graph: str = typer.Option(
        "http://riverbank.example/graph/trusted",
        "--graph", "-g",
        help="Named graph to inspect for contradictions",
    ),
    tentative_graph: str = typer.Option(
        "http://riverbank.example/graph/tentative",
        "--tentative-graph",
        help="Tentative graph where demoted triples are moved",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Detect conflicts but do not apply penalties or move triples",
    ),
) -> None:
    """Detect and demote contradicting triples for functional predicates.

    For each predicate annotated with ``max_cardinality: 1`` in the profile's
    ``predicate_constraints`` block, finds subjects with more than one distinct
    object value.  Reduces confidence of conflicting triples by 30%; demotes
    below-threshold triples to the tentative graph.  Writes ``pgc:ConflictRecord``
    provenance records.

    Example::

        riverbank detect-contradictions docs-policy-v1 --dry-run
    """
    from pathlib import Path  # noqa: PLC0415

    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.pipeline import CompilerProfile  # noqa: PLC0415
    from riverbank.postprocessors.contradiction import ContradictionDetector  # noqa: PLC0415

    profile_path = Path(profile_name)
    if profile_path.exists() and profile_path.suffix in {".yaml", ".yml"}:
        profile = CompilerProfile.from_yaml(profile_path)
    else:
        profile = CompilerProfile(name=profile_name)

    settings = get_settings()
    engine = create_engine(settings.db.dsn)

    rprint(
        f"[bold]riverbank detect-contradictions[/bold]  "
        f"profile={profile.name!r}  graph=<{named_graph}>"
    )
    if dry_run:
        rprint("[dim]dry-run mode — no changes will be written[/dim]")

    detector = ContradictionDetector()
    try:
        with engine.connect() as conn:
            result = detector.detect(
                conn, profile, named_graph,
                tentative_graph=tentative_graph,
                dry_run=dry_run,
            )
            if not dry_run:
                conn.commit()
    except Exception as exc:  # noqa: BLE001
        rprint(f"[red]detect-contradictions failed: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()

    table = Table(
        title="Contradiction detection summary" + (" (DRY RUN)" if dry_run else ""),
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Functional predicates checked", str(result.functional_predicates_checked))
    table.add_row("Conflicts found", str(result.conflicts_found))
    table.add_row("Triples penalised (−30% confidence)", str(result.triples_penalised))
    table.add_row("Triples demoted → tentative", str(result.triples_demoted))
    rprint(table)

    if result.conflict_records:
        cr_table = Table(
            title="Conflict records",
            show_header=True,
            header_style="bold red",
        )
        cr_table.add_column("Subject", max_width=40)
        cr_table.add_column("Predicate", max_width=30)
        cr_table.add_column("Conflicting objects")
        for cr in result.conflict_records[:20]:
            cr_table.add_row(
                cr.subject[:40],
                cr.predicate[:30],
                " | ".join(str(o)[:20] for o in cr.conflicting_objects[:3]),
            )
        rprint(cr_table)

    if result.conflicts_found == 0:
        rprint("[green]No contradictions detected.[/green]")
    elif dry_run:
        rprint(
            f"\n[yellow bold]DRY RUN — {result.conflicts_found} conflict(s) detected. "
            "Remove --dry-run to apply penalties.[/yellow bold]"
        )
    else:
        rprint(
            f"\n[green bold]Done. {result.conflicts_found} conflict(s) processed.[/green bold]"
        )


# ---------------------------------------------------------------------------
# Schema induction
# ---------------------------------------------------------------------------


@app.command("induce-schema")
def induce_schema(
    named_graph: str = typer.Option(
        "http://riverbank.example/graph/trusted",
        "--graph", "-g",
        help="Named graph to analyse for schema induction",
    ),
    output: str = typer.Option(
        "ontology/induced.ttl",
        "--output", "-o",
        help="Output path for the induced Turtle ontology",
    ),
    profile_name: str = typer.Option(
        "", "--profile", "-p",
        help="Profile name or YAML path (optional; updates allowed_predicates/classes if given)",
    ),
    top_predicates: int = typer.Option(
        20, "--top-predicates",
        help="Maximum number of predicates to include in the LLM prompt",
    ),
    top_types: int = typer.Option(
        10, "--top-types",
        help="Maximum number of entity types to include in the LLM prompt",
    ),
) -> None:
    """Cold-start schema induction: propose an OWL ontology from graph statistics.

    Collects unique predicates and entity types from the graph, asks the LLM
    to propose a minimal OWL ontology, and writes it to ``--output`` for human
    review.

    After reviewing and editing ``ontology/induced.ttl``, run a second ingest
    pass with the induced ontology loaded into the profile's
    ``allowed_predicates`` and ``allowed_classes`` blocks.

    Example::

        riverbank induce-schema \\
            --graph http://riverbank.example/graph/trusted \\
            --output ontology/induced.ttl
    """
    from pathlib import Path  # noqa: PLC0415

    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.schema_induction import SchemaInducer  # noqa: PLC0415

    settings = get_settings()
    engine = create_engine(settings.db.dsn)

    rprint(
        f"[bold]riverbank induce-schema[/bold]  "
        f"graph=<{named_graph}>  output={output!r}"
    )
    rprint("[dim]Collecting graph statistics…[/dim]")

    inducer = SchemaInducer(
        settings=settings,
        top_predicates=top_predicates,
        top_types=top_types,
    )

    try:
        with engine.connect() as conn:
            stats = inducer.collect_statistics(conn, named_graph)
    except Exception as exc:  # noqa: BLE001
        rprint(f"[red]Failed to collect statistics: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()

    rprint(
        f"[dim]Statistics: {len(stats.predicates)} predicates, "
        f"{len(stats.types)} entity types found.[/dim]"
    )

    if not stats.predicates and not stats.types:
        rprint(
            "[yellow]No predicates or types found in the graph. "
            "Run riverbank ingest first to populate the graph.[/yellow]"
        )
        return

    rprint("[dim]Requesting ontology proposal from LLM…[/dim]")
    proposal = inducer.propose(stats)

    # Write the Turtle file
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(proposal.ttl_text)

    rprint(f"\n[green bold]Ontology written to {output_path}[/green bold]")
    rprint(
        f"[dim]Predicates addressed: {len(proposal.predicates_addressed)}, "
        f"types: {len(proposal.types_addressed)}, "
        f"model: {proposal.model_used}[/dim]"
    )
    rprint(
        f"[dim]Prompt tokens: {proposal.prompt_tokens}, "
        f"completion tokens: {proposal.completion_tokens}[/dim]"
    )

    if proposal.allowed_predicates:
        rprint(
            f"\n[bold]Suggested profile additions:[/bold]\n"
            f"  allowed_predicates: {proposal.allowed_predicates[:5]}...\n"
            f"  allowed_classes: {proposal.allowed_classes[:5]}..."
        )

    rprint(
        "\n[dim]Review the induced ontology, then run a second ingest pass "
        "with the updated profile for improved precision.[/dim]"
    )


# ---------------------------------------------------------------------------
# Tentative cleanup
# ---------------------------------------------------------------------------


@app.command("gc-tentative")
def gc_tentative(
    tentative_graph: str = typer.Option(
        "http://riverbank.example/graph/tentative",
        "--graph", "-g",
        help="IRI of the tentative graph to clean up",
    ),
    older_than: str = typer.Option(
        "30d",
        "--older-than",
        help="Archive triples older than this duration (e.g. 30d, 7d, 48h)",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Identify stale triples but do not archive them",
    ),
    limit: int = typer.Option(
        1000, "--limit", "-n",
        help="Maximum number of triples to process per run",
    ),
) -> None:
    """Archive stale tentative triples that were never promoted.

    Tentative triples that were extracted but never promoted to the trusted
    graph and whose ``pgc:firstSeen`` timestamp is older than ``--older-than``
    are moved to the ``_riverbank.log`` archive table.

    Run periodically (or automatically after each ingest) to prevent the
    tentative graph from growing indefinitely.

    Example::

        # Preview what would be archived
        riverbank gc-tentative --older-than 30d --dry-run

        # Archive stale triples
        riverbank gc-tentative --older-than 30d
    """
    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.postprocessors.tentative_gc import TentativeGraphCleaner  # noqa: PLC0415

    settings = get_settings()
    engine = create_engine(settings.db.dsn)

    rprint(
        f"[bold]riverbank gc-tentative[/bold]  "
        f"graph=<{tentative_graph}>  older-than={older_than!r}"
    )
    if dry_run:
        rprint("[dim]dry-run mode — no changes will be written[/dim]")

    cleaner = TentativeGraphCleaner(batch_size=limit)
    try:
        with engine.connect() as conn:
            result = cleaner.gc(conn, tentative_graph, ttl=older_than, dry_run=dry_run)
            if not dry_run:
                conn.commit()
    except Exception as exc:  # noqa: BLE001
        rprint(f"[red]gc-tentative failed: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()

    table = Table(
        title="Tentative cleanup summary" + (" (DRY RUN)" if dry_run else ""),
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Cutoff date", result.cutoff_date[:19] if result.cutoff_date else "—")
    table.add_row("Triples examined", str(result.triples_examined))
    table.add_row("Triples archived", str(result.triples_archived))
    table.add_row("Triples within TTL (kept)", str(result.triples_skipped))
    if result.errors:
        table.add_row("[red]Errors[/red]", f"[red]{result.errors}[/red]")
    rprint(table)

    if dry_run:
        rprint(
            f"\n[yellow bold]DRY RUN — {result.triples_archived} triple(s) would be archived. "
            "Remove --dry-run to apply.[/yellow bold]"
        )
    elif result.triples_archived > 0:
        rprint(
            f"\n[green bold]Archived {result.triples_archived} stale tentative triple(s).[/green bold]"
        )
    else:
        rprint("[green]Tentative graph is clean — no stale triples found.[/green]")


# ---------------------------------------------------------------------------
# Quality regression tracking (benchmark)
# ---------------------------------------------------------------------------


@app.command("benchmark")
def benchmark(
    profile_name: str = typer.Option(
        ..., "--profile", "-p",
        help="Profile name or path to YAML file",
    ),
    golden: str = typer.Option(
        ..., "--golden",
        help="Path to the golden corpus directory (must contain ground_truth.yaml)",
    ),
    fail_below_f1: float = typer.Option(
        0.85, "--fail-below-f1",
        help="Exit non-zero when F1 drops below this threshold (0.0–1.0)",
    ),
) -> None:
    """Re-extract a golden corpus and compare against ground truth for quality regression.

    Loads ground truth triples from ``<golden>/ground_truth.yaml``, re-extracts
    the corpus using the current pipeline, and computes precision, recall, and F1.

    Exits with code 1 when ``F1 < --fail-below-f1``.  Designed for use in CI.

    Example::

        riverbank benchmark \\
            --profile docs-policy-v1 \\
            --golden tests/golden/docs-policy-v1 \\
            --fail-below-f1 0.85
    """
    from pathlib import Path  # noqa: PLC0415

    from riverbank.benchmark import BenchmarkRunner  # noqa: PLC0415
    from riverbank.pipeline import CompilerProfile  # noqa: PLC0415

    profile_path = Path(profile_name)
    if profile_path.exists() and profile_path.suffix in {".yaml", ".yml"}:
        profile = CompilerProfile.from_yaml(profile_path)
    else:
        profile = CompilerProfile(name=profile_name)

    golden_dir = Path(golden)
    if not golden_dir.exists():
        rprint(f"[red]Golden corpus directory not found: {golden_dir}[/red]")
        raise typer.Exit(code=1)

    rprint(
        f"[bold]riverbank benchmark[/bold]  "
        f"profile={profile.name!r}  golden={golden!r}  fail-below-f1={fail_below_f1}"
    )

    runner = BenchmarkRunner()
    report = runner.run(
        golden_dir=golden_dir,
        profile=profile,
        fail_below_f1=fail_below_f1,
    )

    table = Table(
        title="Benchmark report",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Ground truth triples", str(report.total_ground_truth))
    table.add_row("Extracted triples", str(report.total_extracted))
    table.add_row("True positives", str(report.true_positives))
    table.add_row("False positives", str(report.false_positives))
    table.add_row("False negatives", str(report.false_negatives))
    table.add_row("Precision", f"{report.precision:.3f}")
    table.add_row("Recall", f"{report.recall:.3f}")
    table.add_row(
        "[bold]F1[/bold]",
        f"[bold {'green' if report.pass_threshold else 'red'}]{report.f1:.3f}[/bold {'green' if report.pass_threshold else 'red'}]",
    )
    table.add_row("Threshold", f"{fail_below_f1:.3f}")
    table.add_row("Result", "[green bold]PASS[/green bold]" if report.pass_threshold else "[red bold]FAIL[/red bold]")
    rprint(table)

    if not report.pass_threshold:
        rprint(
            f"\n[red bold]F1 {report.f1:.3f} is below threshold {fail_below_f1:.3f} — "
            "benchmark FAILED[/red bold]"
        )
        raise typer.Exit(code=1)
    else:
        rprint(f"\n[green bold]Benchmark PASSED (F1={report.f1:.3f})[/green bold]")


# ---------------------------------------------------------------------------
# Extraction feedback loops (v0.13.1)
# ---------------------------------------------------------------------------


@app.command("expand-few-shot")
def expand_few_shot(
    profile_name: str = typer.Option(
        ..., "--profile", "-p",
        help="Profile name or path to profile YAML file",
    ),
    graph: str = typer.Option(
        "http://riverbank.example/graph/trusted",
        "--graph",
        help="Named graph IRI to sample high-confidence triples from",
    ),
    cq_coverage: float = typer.Option(
        0.75, "--cq-coverage",
        help="CQ coverage fraction from the last ingest run (0.0–1.0)",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Compute candidates but do not write to the bank file",
    ),
) -> None:
    """Auto-expand the few-shot example bank with high-confidence triples.

    Samples high-confidence triples from the named graph that satisfy
    competency questions, then appends diverse examples to the profile's
    auto-expansion JSONL bank.  Capped at 15 examples per run to prevent
    the bank from growing monotonically.

    Only runs when ``--cq-coverage`` meets or exceeds the profile's
    ``few_shot.auto_expand_cq_threshold`` (default 0.70).

    Example::

        riverbank expand-few-shot --profile docs-policy-v1 --cq-coverage 0.82
    """
    from pathlib import Path  # noqa: PLC0415

    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.catalog.graph import sparql_query  # noqa: PLC0415
    from riverbank.config import get_settings  # noqa: PLC0415
    from riverbank.few_shot_expansion import FewShotExpander  # noqa: PLC0415
    from riverbank.pipeline import CompilerProfile  # noqa: PLC0415

    settings = get_settings()

    profile_path = Path(profile_name)
    if profile_path.exists() and profile_path.suffix in {".yaml", ".yml"}:
        profile = CompilerProfile.from_yaml(profile_path)
    else:
        profile = CompilerProfile(name=profile_name)

    few_shot_cfg: dict = getattr(profile, "few_shot", {})
    if not few_shot_cfg.get("auto_expand", False):
        rprint("[yellow]Auto-expansion is disabled in this profile "
               "(set few_shot.auto_expand: true to enable).[/yellow]")
        raise typer.Exit(code=0)

    expander = FewShotExpander(
        cq_threshold=float(few_shot_cfg.get("auto_expand_cq_threshold", 0.70)),
        confidence_threshold=float(few_shot_cfg.get("auto_expand_confidence", 0.85)),
        max_bank_size=int(few_shot_cfg.get("max_bank_size", 15)),
    )
    bank_path = expander.bank_path_for_profile(profile)

    # Fetch high-confidence triples from the graph
    engine = create_engine(settings.db.dsn)
    triples: list[dict] = []
    try:
        with engine.connect() as conn:
            sparql = f"""\
SELECT ?s ?p ?o ?confidence ?evidence WHERE {{
  GRAPH <{graph}> {{
    ?s ?p ?o .
    ?s <http://riverbank.example/pgc/confidence> ?confidence .
    OPTIONAL {{ ?s <http://riverbank.example/pgc/evidenceExcerpt> ?evidence . }}
    FILTER(?confidence >= {expander._confidence_threshold})
  }}
}}
LIMIT 500
"""
            rows = sparql_query(conn, sparql)
            for row in rows:
                from types import SimpleNamespace  # noqa: PLC0415
                triple = SimpleNamespace(
                    subject=str(row.get("s", "")),
                    predicate=str(row.get("p", "")),
                    object_value=str(row.get("o", "")),
                    confidence=float(row.get("confidence", 0.9)),
                    evidence=SimpleNamespace(excerpt=str(row.get("evidence", ""))),
                )
                triples.append(triple)
    except Exception as exc:  # noqa: BLE001
        rprint(f"[red]Failed to fetch triples from graph: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    rprint(
        f"[bold]riverbank expand-few-shot[/bold]  "
        f"profile={profile.name!r}  graph={graph!r}  "
        f"cq_coverage={cq_coverage:.0%}  dry_run={dry_run}"
    )
    rprint(f"  Candidate triples fetched: {len(triples)}")

    result = expander.expand(
        triples=triples,
        bank_path=bank_path,
        cq_coverage=cq_coverage,
        competency_questions=getattr(profile, "competency_questions", []),
        dry_run=dry_run,
    )

    if not result.threshold_met:
        rprint(
            f"[yellow]CQ coverage {cq_coverage:.0%} is below threshold "
            f"{expander._cq_threshold:.0%} — expansion skipped.[/yellow]"
        )
        raise typer.Exit(code=0)

    rprint(f"  Examples added: [green]{result.examples_added}[/green]")
    rprint(f"  Skipped (confidence): {result.examples_skipped_confidence}")
    rprint(f"  Skipped (diversity): {result.examples_skipped_diversity}")
    rprint(f"  Skipped (CQ relevance): {result.examples_skipped_cq}")
    rprint(f"  Bank size after: {result.bank_size_after}")
    if not dry_run:
        rprint(f"\n[green bold]Bank written to {bank_path}[/green bold]")
    else:
        rprint("\n[yellow](dry-run — no changes written)[/yellow]")


@app.command("build-knowledge-context")
def build_knowledge_context(
    profile_name: str = typer.Option(
        ..., "--profile", "-p",
        help="Profile name or path to profile YAML file",
    ),
    fragment: str = typer.Option(
        ..., "--fragment",
        help="Fragment text to build the knowledge context for",
    ),
    graph: str = typer.Option(
        "http://riverbank.example/graph/trusted",
        "--graph",
        help="Named graph IRI to query for context",
    ),
) -> None:
    """Preview the KNOWN GRAPH CONTEXT block that would be injected for a fragment.

    Queries the graph for entities mentioned in the fragment text and renders
    the structured context block that would be prepended to the extraction
    prompt.  Useful for diagnosing knowledge-prefix adapter behaviour.

    Example::

        riverbank build-knowledge-context \\
            --profile docs-policy-v1 \\
            --fragment "The Sesam pipe connects to the Salesforce source."
    """
    from pathlib import Path  # noqa: PLC0415

    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.config import get_settings  # noqa: PLC0415
    from riverbank.extractors.knowledge_prefix import KnowledgePrefixAdapter  # noqa: PLC0415
    from riverbank.pipeline import CompilerProfile  # noqa: PLC0415

    settings = get_settings()

    profile_path = Path(profile_name)
    if profile_path.exists() and profile_path.suffix in {".yaml", ".yml"}:
        profile = CompilerProfile.from_yaml(profile_path)
    else:
        profile = CompilerProfile(name=profile_name)

    kp_cfg: dict = getattr(profile, "knowledge_prefix", {})
    if not kp_cfg.get("enabled", False):
        rprint("[yellow]Knowledge-prefix adapter is disabled in this profile "
               "(set knowledge_prefix.enabled: true to enable).[/yellow]")
        raise typer.Exit(code=0)

    adapter = KnowledgePrefixAdapter.from_profile(profile)

    engine = create_engine(settings.db.dsn)
    try:
        with engine.connect() as conn:
            result = adapter.build_context(conn, graph, fragment)
    except Exception as exc:  # noqa: BLE001
        rprint(f"[red]Failed to query graph: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    rprint(
        f"[bold]riverbank build-knowledge-context[/bold]  "
        f"profile={profile.name!r}  graph={graph!r}"
    )
    rprint(f"  Entities found: {result.entities_found}")
    rprint(f"  Triples injected: {result.triples_injected}")
    rprint(f"  Tokens used (~words): {result.tokens_used}")

    if result.context_block:
        rprint("\n[bold cyan]Context block:[/bold cyan]")
        rprint(result.context_block)
    else:
        rprint("[yellow]No matching entities found — context block is empty.[/yellow]")


