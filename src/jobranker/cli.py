"""Command-line entry point. Later milestones attach subcommands to `app`."""

import contextlib
import os
import socket
import time
import webbrowser
from datetime import timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import httpx
import typer
import uvicorn
from fastapi import FastAPI
from rich.console import Console

from jobranker import judging
from jobranker.collect import DEFAULT_MAX_RESULTS, collect, utc_now
from jobranker.config import ConfigError, load_companies, load_searches, read_token
from jobranker.display import RunDisplay, summary
from jobranker.judge.base import Judge, JudgeFailure, JudgeUnavailable
from jobranker.judge.claude_code import DEFAULT_MODEL, ClaudeCodeJudge, check_ready
from jobranker.models import Verdict
from jobranker.profile import EXAMPLE, Profile, ProfileError, load_profile
from jobranker.rules import RULES_VERSION, Reason
from jobranker.screening import apply_rules
from jobranker.sources import linkedin
from jobranker.store import Store, StoredPosting, StoreError
from jobranker.web.app import create_app

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


def make_console() -> Console:
    """The console for the progress display. Tests replace this function."""
    return Console()


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
    quiet: Annotated[
        bool, typer.Option("--quiet", help="Plain lines only, without the bar and the spinner.")
    ] = False,
) -> None:
    """Fetch postings from the company feeds and the searches and store them."""
    try:
        company_list = load_companies(companies)
        search_list = load_searches(searches)
        token = read_token(os.environ, env_file)
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from None
    if not company_list and not search_list:
        typer.echo(NO_CONFIGURATION, err=True)
        raise typer.Exit(1)

    try:
        store = Store(db)
    except StoreError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from None
    console = make_console()
    # The bar is only drawn on a real terminal, never into a file, a pipe or a scheduled job.
    live = console.is_terminal and not quiet
    started = time.monotonic()
    display = RunDisplay(console, len(company_list) + len(search_list), live=live)
    with make_client() as client, store, display:
        reports = collect(
            company_list,
            search_list,
            store,
            client,
            token=token,
            max_results=max_results,
            actor=actor,
            on_start=display.start,
            on_finish=display.finish,
        )
    display.line(summary(reports, time.monotonic() - started))
    if all(report.error is not None for report in reports):
        raise typer.Exit(1)


ProfileOption = Annotated[Path, typer.Option(help="Private profile. Not committed.")]
DatabaseOption = Annotated[Path, typer.Option(help="SQLite file the postings are stored in.")]
NO_RESULTS = "No rule results for this profile. Run `jobrank rules` first."
NO_POSTINGS = "No postings are stored. Run `jobrank collect` first."
NOTHING_PASSED = "No posting passed the rules."
# About a hundred years. A larger number cannot be subtracted from a date.
MAX_DAYS = 36500


def _open(profile: Path, db: Path) -> tuple[Profile, Store]:
    """Load the profile and open the store, or stop with a short message."""
    try:
        loaded = load_profile(profile)
        # Opening a missing file would create it, which hides a mistyped path.
        if not db.is_file():
            raise StoreError(f"{db}: not found. Run `jobrank collect` first.")
        return loaded, Store(db)
    except (ProfileError, StoreError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from None


@app.command("rules")
def rules_command(
    profile: ProfileOption = Path("profile.yaml"),
    db: DatabaseOption = Path("data/ranker.db"),
) -> None:
    """Drop the stored postings that cannot fit the profile. Sends no request."""
    loaded, store = _open(profile, db)
    with store:
        checked = apply_rules(store, loaded, utc_now())
        counts = store.rule_counts(loaded.digest, RULES_VERSION)
    typer.echo(f"checked {checked}")
    for reason in Reason:
        typer.echo(f"{reason.value}: {counts.get(reason.value, 0)}")
    typer.echo(f"passed {counts['passed']} postings in {counts['groups']} groups")


@app.command("list")
def list_command(
    profile: ProfileOption = Path("profile.yaml"),
    db: DatabaseOption = Path("data/ranker.db"),
    days: Annotated[
        int | None,
        typer.Option(min=1, max=MAX_DAYS, help="Only postings first seen in the last N days."),
    ] = None,
    limit: Annotated[int, typer.Option(min=1, help="Most postings to print.")] = 50,
) -> None:
    """Print the postings that passed the rules, newest first. Sends no request."""
    loaded, store = _open(profile, db)
    since = None if days is None else utc_now() - timedelta(days=days)
    with store:
        stored_count = store.count()
        counts = store.rule_counts(loaded.digest, RULES_VERSION)
        groups = store.passed_groups(loaded.digest, RULES_VERSION, since=since, limit=limit)
    if not stored_count:
        typer.echo(NO_POSTINGS)
    elif not counts["checked"]:
        typer.echo(NO_RESULTS)
    elif not counts["groups"]:
        typer.echo(NOTHING_PASSED)
    elif not groups:
        typer.echo(f"No posting that passed the rules was first seen in the last {days} days.")
    for stored in groups:
        posting = stored.posting
        typer.echo(f"{posting.company} | {posting.title} | {posting.location}")
        typer.echo(f"  {posting.url}")


DEFAULT_JUDGE_LIMIT = 40
STOP_MESSAGES = {
    judging.PLAN_LIMIT: "Stopped: the plan limit is reached. Run again after it resets.",
    judging.SPEND_LIMIT: (
        "Stopped: a spend limit of usage credits is reached. Usage credits are on in the"
        " account, so calls may have been billed. Turn them off in the account settings."
    ),
    judging.FAILURES: "Stopped: three calls failed in a row.",
}


def make_judge(model: str) -> Judge:
    """The real judge, after the checks that it can run and is not billed. Tests replace this."""
    check_ready()
    return ClaudeCodeJudge(model)


def _report(stored: StoredPosting, outcome: Verdict | JudgeFailure) -> None:
    # Company and title only, as `list` prints them. The reasons stay in the database.
    name = f"{stored.posting.company} | {stored.posting.title}"
    if isinstance(outcome, Verdict):
        typer.echo(f"{outcome.decision:<4} {name}")
    else:
        typer.echo(f"fail {name} ({outcome.reason})")


@app.command("judge")
def judge_command(
    profile: ProfileOption = Path("profile.yaml"),
    db: DatabaseOption = Path("data/ranker.db"),
    limit: Annotated[
        int, typer.Option(min=1, help="Most postings to judge in this run.")
    ] = DEFAULT_JUDGE_LIMIT,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print how many postings wait, and judge nothing.")
    ] = False,
    model: Annotated[str, typer.Option(help="The model that judges.")] = DEFAULT_MODEL,
) -> None:
    """Have Claude say yes or no to the postings that passed the rules.

    Sends each posting and the judge's part of the profile to the model provider through
    Claude Code, on its plan login.
    """
    loaded, store = _open(profile, db)
    with store:
        apply_rules(store, loaded, utc_now())
        if dry_run:
            count = len(judging.waiting(store, loaded, model))
            noun = "posting waits" if count == 1 else "postings wait"
            typer.echo(f"{count} {noun} to be judged")
            return
        if not loaded.roles and not loaded.skills:
            # Without them every answer would be a guess, paid for from the plan limit.
            typer.echo(
                f"{profile} has no `roles` and no `skills`, so the judge has nothing to compare"
                f" a posting with. Add them as in {EXAMPLE}.",
                err=True,
            )
            raise typer.Exit(1)
        try:
            judge = make_judge(model)
        except JudgeUnavailable as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(1) from None
        tally = judging.run(store, loaded, judge, limit=limit, now=utc_now, report=_report)
    typer.echo(f"yes {tally.yes}, no {tally.no}, failed {tally.failed}, waiting {tally.waiting}")
    if tally.stopped is not None:
        typer.echo(STOP_MESSAGES[tally.stopped], err=True)
        raise typer.Exit(1)


# The dashboard answers on this machine only. No other address is ever bound.
LOCAL_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def make_server(application: FastAPI) -> uvicorn.Server:
    """The server for the dashboard: quiet, and without a header that names its software."""
    config = uvicorn.Config(
        application,
        log_level="warning",
        access_log=False,
        server_header=False,
        proxy_headers=False,
    )
    return uvicorn.Server(config)


def serve(application: FastAPI, listener: socket.socket) -> None:
    """Answer requests on the bound socket until Ctrl+C. Tests replace this function."""
    make_server(application).run(sockets=[listener])


def open_browser(address: str) -> None:
    """Show the dashboard in the default browser. Tests replace this function."""
    webbrowser.open(address)


@app.command("dashboard")
def dashboard_command(
    profile: ProfileOption = Path("profile.yaml"),
    db: DatabaseOption = Path("data/ranker.db"),
    port: Annotated[
        int, typer.Option(min=1024, max=65535, help="Local port the dashboard answers on.")
    ] = DEFAULT_PORT,
    no_open: Annotated[bool, typer.Option("--no-open", help="Do not open the browser.")] = False,
) -> None:
    """Show the postings that passed the rules in the browser. Answers on this machine only."""
    loaded, store = _open(profile, db)
    with store:
        apply_rules(store, loaded, utc_now())
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # The socket is bound here and not by the server, so a taken port is reported
        # in one line, and the address is fixed to this machine in one place.
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((LOCAL_HOST, port))
        listener.listen()
    except OSError:
        listener.close()
        typer.echo(f"Port {port} cannot be used. Choose another one with --port.", err=True)
        raise typer.Exit(1) from None
    address = f"http://{LOCAL_HOST}:{port}"
    typer.echo(f"Dashboard at {address} (stop with Ctrl+C)")
    with listener:
        if not no_open:
            open_browser(address)
        # Ctrl+C is the way to stop the dashboard, so it is not reported as a failure.
        with contextlib.suppress(KeyboardInterrupt):
            serve(create_app(db, loaded, port=port), listener)
    typer.echo("Dashboard stopped.")
