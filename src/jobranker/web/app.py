"""The dashboard application: pages built on the server from the stored postings.

It shows text that third parties wrote and it can change stored data. So every text is
escaped, every answer carries the safety headers, and a request is served only when it
names this machine, and changes data only with the token of this start.
"""

import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, PackageLoader, StrictUndefined
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from jobranker.collect import utc_now
from jobranker.profile import Profile
from jobranker.rules import RULES_VERSION
from jobranker.screening import apply_rules
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
_TAB_PATHS = {"applied": APPLIED, "dismissed": DISMISSED}
# The longest row number that is accepted. SQLite cannot hold a longer one.
_ID_DIGITS = 18
# Only the files of this application may load, nothing may frame it, forms post to it only.
SAFETY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    # The referrer stays inside the application. With no referrer at all, a browser sends
    # a plain form with `Origin: null`, and the guard would refuse the dashboard's own forms.
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
}
_READING_METHODS = frozenset({"GET", "HEAD"})
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
    # None for a tab that shows only its latest rows, where a number would look like a total.
    count: int | None


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


class Guard:
    """The outermost layer: refuses requests meant for another machine, adds the headers.

    A page on another site can make the browser send a request here. The `Host` check
    stops a foreign name that was pointed at this machine, and the `Origin` check stops
    a form or a script of another site. The port is compared too, so another local
    program is not mistaken for this one.
    """

    def __init__(self, app: ASGIApp, port: int) -> None:
        self._app = app
        self._hosts = frozenset({f"127.0.0.1:{port}", f"localhost:{port}"})
        self._origins = frozenset(f"http://{host}" for host in self._hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SAFETY_HEADERS.items():
                    headers[name] = value
            await send(message)

        headers = Headers(scope=scope)
        hosts = headers.getlist("host")
        if len(hosts) != 1 or hosts[0].lower() not in self._hosts:
            refusal = PlainTextResponse("This address is not served by the dashboard.", 400)
            await refusal(scope, receive, with_headers)
            return
        # A browser names the page a changing request comes from. No name is allowed here,
        # because the token is still required, but a wrong name is refused at once.
        origins = headers.getlist("origin")
        if scope["method"] not in _READING_METHODS and any(o not in self._origins for o in origins):
            refusal = PlainTextResponse("This request came from another page.", 403)
            await refusal(scope, receive, with_headers)
            return
        await self._app(scope, receive, with_headers)


def _query(value: str) -> str:
    """The search text of a request: single spaces, cut at the limit."""
    return " ".join(value.split())[:QUERY_LIMIT].strip()


def _row_id(value: str) -> int | None:
    """The row number a form names, or None when the field holds anything else."""
    if value.isascii() and value.isdigit() and len(value) <= _ID_DIGITS:
        return int(value)
    return None


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
    app.add_middleware(Guard, port=port)
    # New at each start and kept in memory only, so a token of an earlier start is worthless.
    token = secrets.token_urlsafe(32)
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
        }
        tabs = [Tab(path, label, counts.get(path)) for path, label in _TAB_LABELS.items()]
        page = templates.get_template(name).render(tabs=tabs, active=active, token=token, **context)
        return HTMLResponse(page)

    @app.exception_handler(Exception)
    def failed(request: Request, error: Exception) -> PlainTextResponse:
        # This answer is sent outside the guard, so it carries the headers itself.
        return PlainTextResponse(
            "The dashboard hit an error. The terminal shows what happened.",
            500,
            headers=SAFETY_HEADERS,
        )

    # The version mark of the store at the last rule run. Empty before the first request.
    checked: list[int] = []

    @contextmanager
    def opened() -> Iterator[Store]:
        """The store for one page request, with the rules applied to what is new.

        A SQLite connection belongs to one thread, so each request opens its own store.
        A collection run can store postings while the dashboard is open. They get their
        rule results here, so a reload shows them. Looking for postings without a result
        reads every posting, so it is done only when something was stored since the last time.
        """
        with Store(db) as store:
            mark = store.version_mark()
            if checked != [mark]:
                apply_rules(store, profile, now())
                checked[:] = [mark]
            yield store

    @app.get(REVIEW, response_class=HTMLResponse)
    def review(entry: str = "", q: str = "", page: str = "1") -> HTMLResponse:
        only_entry = entry == "1"
        query = _query(q)
        moment = now()
        with opened() as store:
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
            elif not store.count():
                empty = "No jobs yet. Run `jobrank collect` in the terminal, then reload this page."
            elif not store.rule_counts(profile.digest, RULES_VERSION)["groups"]:
                empty = (
                    "No job passed the rules. Run `jobrank collect` in the terminal to look"
                    " for new jobs, or widen the rules in profile.yaml and start the"
                    " dashboard again."
                )
            else:
                empty = (
                    "Everything is reviewed. Run `jobrank collect` in the terminal"
                    " to look for new jobs, then reload this page."
                )
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
                tab="review",
            )

    def decided(path: str, one: str, many: str) -> HTMLResponse:
        moment = now()
        stamped = path == APPLIED
        with opened() as store:
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
                tab=path.strip("/"),
            )

    @app.get(APPLIED, response_class=HTMLResponse)
    def applied() -> HTMLResponse:
        return decided(APPLIED, "application", "applications")

    @app.get(DISMISSED, response_class=HTMLResponse)
    def dismissed() -> HTMLResponse:
        return decided(DISMISSED, "job not for me", "jobs not for me")

    @app.get(RUNS, response_class=HTMLResponse)
    def runs() -> HTMLResponse:
        with opened() as store:
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

    def allowed(sent: str) -> bool:
        return secrets.compare_digest(sent.encode(), token.encode())

    def refused() -> PlainTextResponse:
        return PlainTextResponse("This request did not come from the dashboard page.", 403)

    def unclear() -> PlainTextResponse:
        return PlainTextResponse("This request names no job and decision the dashboard knows.", 400)

    def back(tab: str, entry: str = "", q: str = "", page: str = "1") -> RedirectResponse:
        """Send the browser to the tab it came from. No posted address is ever used."""
        target = _TAB_PATHS.get(tab) or review_address(entry == "1", _query(q), _page_number(page))
        return RedirectResponse(target, status_code=303)

    @app.post("/decide")
    def decide(
        posting: str = Form(""),
        decision: str = Form(""),
        token: str = Form(""),
        tab: str = Form(""),
        entry: str = Form(""),
        q: str = Form(""),
        page: str = Form("1"),
    ) -> Response:
        if not allowed(token):
            return refused()
        row = _row_id(posting)
        if row is None or decision not in set(Decision):
            return unclear()
        with Store(db) as store:
            if not store.decide(row, Decision(decision), now()):
                return PlainTextResponse("This job is not stored.", 404)
        return back(tab, entry, q, page)

    @app.post("/undo")
    def undo(posting: str = Form(""), token: str = Form(""), tab: str = Form("")) -> Response:
        if not allowed(token):
            return refused()
        row = _row_id(posting)
        if row is None:
            return unclear()
        with Store(db) as store:
            store.undo(row)
        return back(tab)

    return app


def _run_row(summary: RunSummary) -> RunRow:
    started = summary.started_at
    return RunRow(
        started=f"{_day(started)} {started.astimezone().year}, {_minute(started)}",
        sources=summary.sources,
        not_collected=summary.not_collected,
        new=summary.new,
    )
