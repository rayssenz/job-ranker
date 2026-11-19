"""Command-line entry point. Later milestones attach subcommands to `app`."""

import os
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import httpx
import typer

from jobranker.collect import DEFAULT_MAX_RESULTS, collect
from jobranker.config import ConfigError, load_companies, load_searches, read_token
from jobranker.sources import linkedin
from jobranker.store import Store, StoreError

FEED_TIMEOUT_SECONDS = 20.0
NO_CONFIGURATION = (
    "No configuration found. Copy config/companies.example.yaml to config/companies.yaml"
    " or config/searches.example.yaml to config/searches.yaml."
)

# Local variables are kept out of tracebacks because one of them can be a token.
app = typer.Typer(
    help="Collect job postings, rank them, and measure the ranking.",
    pretty_exceptions_show_locals=False,
)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"jobrank {version('jobranker')}")
        raise typer.Exit


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    show_version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_print_version, is_eager=True, help="Show the version and exit."
        ),
    ] = False,
) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit


def make_client() -> httpx.Client:
    """The HTTP client for a run. Tests replace this function."""
    return httpx.Client(
        timeout=FEED_TIMEOUT_SECONDS,
        headers={"User-Agent": f"jobranker/{version('jobranker')}"},
    )


@app.command("collect")
def collect_command(
    companies: Annotated[Path, typer.Option(help="Company list. Not committed.")] = Path(
        "config/companies.yaml"
    ),
    searches: Annotated[Path, typer.Option(help="Search list. Not committed.")] = Path(
        "config/searches.yaml"
    ),
    db: Annotated[Path, typer.Option(help="SQLite file to store postings in.")] = Path(
        "data/ranker.db"
    ),
    env_file: Annotated[
        Path, typer.Option(help="File to read APIFY_TOKEN from when it is not in the environment.")
    ] = Path(".env"),
    max_results: Annotated[
        int, typer.Option(min=1, help="Most search results to ask for in one run. Each is billed.")
    ] = DEFAULT_MAX_RESULTS,
    actor: Annotated[
        str, typer.Option(help="Apify actor that runs the LinkedIn search.")
    ] = linkedin.DEFAULT_ACTOR,
) -> None:
    """Fetch postings from the company feeds and the searches and store them."""
    try:
        company_list = load_companies(companies)
        search_list = load_searches(searches)
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from None
    if not company_list and not search_list:
        typer.echo(NO_CONFIGURATION, err=True)
        raise typer.Exit(1)

    token = read_token(os.environ, env_file)
    try:
        store = Store(db)
    except StoreError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from None
    with make_client() as client, store:
        reports = collect(
            company_list,
            search_list,
            store,
            client,
            token=token,
            max_results=max_results,
            actor=actor,
        )
    for report in reports:
        typer.echo(report.line())
    if all(report.error is not None for report in reports):
        raise typer.Exit(1)
