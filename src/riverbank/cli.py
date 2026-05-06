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
) -> None:
    """Execute a SPARQL SELECT or ASK query against the compiled knowledge graph.

    Routes the query through pg_ripple.sparql_query().  Falls back with a
    warning when pg_ripple is not installed.
    """
    import json as _json  # noqa: PLC0415

    from sqlalchemy import create_engine  # noqa: PLC0415

    from riverbank.catalog.graph import sparql_query  # noqa: PLC0415

    settings = get_settings()
    engine = create_engine(settings.db.dsn)
    try:
        with engine.connect() as conn:
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
        rprint(
            "[yellow]Full lint (beyond --shacl-only) is planned for v0.5.0.  "
            "Pass --shacl-only to run the SHACL quality gate now.[/yellow]"
        )
        raise typer.Exit(code=0)

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

