from __future__ import annotations

import sys
from typing import Optional

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
                rprint("       [dim]pg-tide is optional — CDC relay features will be unavailable[/dim]")

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
    """Initialise the _riverbank schema by running Alembic migrations."""
    from alembic import command  # noqa: PLC0415
    from alembic.config import Config  # noqa: PLC0415

    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    rprint("[green]✓[/green]  schema migrations applied")


@app.command()
def ingest(
    corpus: str = typer.Argument(..., help="Path to a corpus directory or file"),
    profile: str = typer.Option("default", "--profile", "-p", help="Compiler profile name"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Parse and fragment only; skip extraction"),
) -> None:
    """Ingest a document corpus into the knowledge graph (Phase 1 — v0.2.0)."""
    rprint("[yellow]ingest not yet implemented — arriving in v0.2.0[/yellow]")
    raise typer.Exit(code=0)


@app.command()
def query(
    sparql: str = typer.Argument(..., help="SPARQL SELECT or CONSTRUCT query string"),
) -> None:
    """Query the compiled knowledge graph (Phase 2 — v0.3.0)."""
    rprint("[yellow]query not yet implemented — arriving in v0.3.0[/yellow]")
    raise typer.Exit(code=0)
