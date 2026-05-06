from __future__ import annotations

import typer
from rich import print as rprint
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
        with psycopg.connect(dsn) as conn:
            # pg-trickle preflight — returns (check_name, ok, detail)
            rows = conn.execute("SELECT * FROM pgtrickle.preflight()").fetchall()
            for row in rows:
                check, ok = row[0], row[1]
                detail = row[2] if len(row) > 2 else ""
                icon = "[green]✓[/green]" if ok else "[red]✗[/red]"
                rprint(f"  {icon}  pg_trickle  {check:<32} {detail}")
                if not ok:
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

    pipeline = IngestPipeline()

    rprint(f"[bold]riverbank ingest[/bold]  corpus={corpus!r}  profile={profile.name!r}")
    if dry_run:
        rprint("[dim]dry-run mode — extraction and graph writes are skipped[/dim]")

    stats = pipeline.run(corpus_path=corpus, profile=profile, dry_run=dry_run, mode=mode)

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
    table.add_row("Estimated cost (USD)", f"{stats['cost_usd']:.6f}")
    table.add_row("Errors", str(stats["errors"]))

    rprint(table)

    if stats["errors"] > 0:
        rprint(f"[red bold]{stats['errors']} error(s) — see logs for details[/red bold]")
        raise typer.Exit(code=1)

    rprint("[green bold]ingest complete[/green bold]")


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
) -> None:
    """Execute a SPARQL SELECT or ASK query against the compiled knowledge graph.

    Routes the query through pg_ripple.sparql_query().  Falls back with a
    warning when pg_ripple is not installed.

    With ``--expand term1,term2`` the terms are looked up in the
    ``<thesaurus>`` named graph (``skos:altLabel``, ``skos:related``,
    ``skos:exactMatch``, ``skos:closeMatch``) and the expanded synonym set is
    logged before the query is dispatched.
    """
    import json as _json  # noqa: PLC0415

    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.catalog.graph import sparql_query, sparql_query_with_thesaurus  # noqa: PLC0415

    settings = get_settings()
    engine = create_engine(settings.db.dsn)
    try:
        with engine.connect() as conn:
            if expand:
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
    table = Table(title="SPARQL results", show_header=True, header_style="bold cyan")
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


# ---------------------------------------------------------------------------
# review sub-app  (v0.6.0)
# ---------------------------------------------------------------------------

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

