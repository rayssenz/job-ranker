"""The dashboard application: pages built on the server from the stored postings."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, PackageLoader, StrictUndefined

from jobranker.collect import utc_now
from jobranker.profile import Profile
from jobranker.rules import RULES_VERSION
from jobranker.store import Decision, RunSummary, Store, StoredPosting
from jobranker.web import view

PAGE_SIZE = 50
RUNS_SHOWN = 10
# A longer search text is cut, so a pasted page of text cannot fill the address.
QUERY_LIMIT = 100
_PACKAGE = "jobranker.web"

REVIEW, APPLIED, DISMISSED, RUNS = "/", "/applied", "/dismissed", "/runs"
_TAB_LABELS = {REVIEW: "To review", APPLIED: "Applied", DISMISSED: "Not for me", RUNS: "Runs"}
_DECISION_OF = {APPLIED: Decision.APPLIED, DISMISSED: Decision.DISMISSED}
_EMPTY = {
    APPLIED: "No applications yet. Mark a job as Applied on the To review tab and it lands here.",
    DISMISSED: "Nothing marked not for me. Jobs you set aside on the To review tab land here.",
}


@dataclass(frozen=True)
class Card:
    """What one card shows. Every field is plain text that the template escapes."""

    id: int
    title: str
    company: str
    location: str
    found: str
    fresh: bool
    excerpt: str
    cut: bool
    description: str
    link: str | None
    stamp: str | None = None


@dataclass(frozen=True)
class Tab:
    path: str
    label: str
    count: int


@dataclass(frozen=True)
class RunRow:
    started: str
    sources: int
    not_collected: int
    new: int


def _plural(number: int, one: str, many: str) -> str:
    return f"{number} {one if number == 1 else many}"


def _day(moment: datetime) -> str:
    """The day in the time zone of this machine, as in `17 Nov`."""
    local = moment.astimezone()
    return f"{local.day} {local:%b}"


def _minute(moment: datetime) -> str:
    return f"{moment.astimezone():%H:%M}"


def _card(stored: StoredPosting, now: datetime, decided_at: datetime | None = None) -> Card:
    posting = stored.posting
    short, cut = view.excerpt(posting.description)
    source = view.SOURCE_NAMES.get(posting.source, posting.source)
    return Card(
        id=stored.id,
        title=posting.title,
        company=posting.company,
        location=posting.location,
        found=f"{source}, {view.age(stored.first_seen, now)}",
        fresh=view.is_new(stored.first_seen, now),
        excerpt=short,
        cut=cut,
        description=posting.description,
        link=view.safe_link(posting.url),
        stamp=None if decided_at is None else f"Applied {_day(decided_at)}",
    )


def _page_number(value: str) -> int:
    """The page a request asks for. Anything that is not a number means the first page."""
    try:
        return max(1, int(value))
    except ValueError:
        return 1


def review_address(entry: bool, query: str, page: int) -> str:
    """The address of a view of the review tab, built from checked values only."""
    values = {}
    if entry:
        values["entry"] = "1"
    if query:
        values["q"] = query
    if page > 1:
        values["page"] = str(page)
    return REVIEW + (f"?{urlencode(values)}" if values else "")


def create_app(
    db: Path, profile: Profile, *, port: int, now: Callable[[], datetime] = utc_now
) -> FastAPI:
    """The application for one database and one profile, as it runs on `port`."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    # Escaping is on for every template, so no text of a posting can become markup.
    templates = Environment(
        loader=PackageLoader(_PACKAGE), autoescape=True, undefined=StrictUndefined
    )
    app.mount("/static", StaticFiles(packages=[(_PACKAGE, "static")]), name="static")

    def render(name: str, store: Store, active: str, **context: object) -> HTMLResponse:
        counts = {
            REVIEW: len(store.review_groups(profile.digest, RULES_VERSION)),
            APPLIED: len(store.decided_groups(Decision.APPLIED)),
            DISMISSED: len(store.decided_groups(Decision.DISMISSED)),
            RUNS: len(store.run_summaries(RUNS_SHOWN)),
        }
        tabs = [Tab(path, label, counts[path]) for path, label in _TAB_LABELS.items()]
        page = templates.get_template(name).render(tabs=tabs, active=active, **context)
        return HTMLResponse(page)

    # A SQLite connection belongs to one thread, so each request opens its own store.
    @app.get(REVIEW, response_class=HTMLResponse)
    def review(entry: str = "", q: str = "", page: str = "1") -> HTMLResponse:
        only_entry = entry == "1"
        query = " ".join(q.split())[:QUERY_LIMIT].strip()
        moment = now()
        with Store(db) as store:
            groups = store.review_groups(profile.digest, RULES_VERSION)
            kept = [
                stored
                for stored in groups
                if (not only_entry or view.is_entry_level(stored.posting.title, profile))
                and view.matches(stored.posting, query)
            ]
            pages = max(1, -(-len(kept) // PAGE_SIZE))
            number = min(_page_number(page), pages)
            shown = kept[(number - 1) * PAGE_SIZE : number * PAGE_SIZE]
            if kept:
                empty = ""
            elif groups:
                empty = "No job matches. Clear the search or turn the switch off."
            elif store.count():
                empty = (
                    "Everything is reviewed. Run `jobrank collect` in the terminal"
                    " to look for new jobs, then reload this page."
                )
            else:
                empty = "No jobs yet. Run `jobrank collect` in the terminal, then reload this page."
            latest = store.run_summaries(1)
            return render(
                "cards.html",
                store,
                REVIEW,
                heading=f"{_plural(len(groups), 'job', 'jobs')} to review",
                cards=[_card(stored, moment) for stored in shown],
                empty=empty,
                filters=True,
                filtered=only_entry or bool(query),
                entry=only_entry,
                query=query,
                kept=len(kept),
                total=len(groups),
                page=number,
                pages=pages,
                previous=review_address(only_entry, query, number - 1) if number > 1 else None,
                next=review_address(only_entry, query, number + 1) if number < pages else None,
                run=_run_row(latest[0]) if latest else None,
            )

    def decided(path: str, one: str, many: str) -> HTMLResponse:
        moment = now()
        stamped = path == APPLIED
        with Store(db) as store:
            groups = store.decided_groups(_DECISION_OF[path])
            cards = [_card(stored, moment, at if stamped else None) for stored, at in groups]
            return render(
                "cards.html",
                store,
                path,
                heading=_plural(len(groups), one, many),
                cards=cards,
                empty="" if cards else _EMPTY[path],
                filters=False,
            )

    @app.get(APPLIED, response_class=HTMLResponse)
    def applied() -> HTMLResponse:
        return decided(APPLIED, "application", "applications")

    @app.get(DISMISSED, response_class=HTMLResponse)
    def dismissed() -> HTMLResponse:
        return decided(DISMISSED, "job not for me", "jobs not for me")

    @app.get(RUNS, response_class=HTMLResponse)
    def runs() -> HTMLResponse:
        with Store(db) as store:
            summaries = store.run_summaries(RUNS_SHOWN)
            failures = store.run_failures(summaries[0].run_id) if summaries else []
            return render(
                "runs.html",
                store,
                RUNS,
                heading="Runs",
                runs=[_run_row(summary) for summary in summaries],
                failures=[
                    (view.SOURCE_NAMES.get(source, source), target, error)
                    for source, target, error in failures
                ],
            )

    return app


def _run_row(summary: RunSummary) -> RunRow:
    started = summary.started_at
    return RunRow(
        started=f"{_day(started)} {started.astimezone().year}, {_minute(started)}",
        sources=summary.sources,
        not_collected=summary.not_collected,
        new=summary.new,
    )
