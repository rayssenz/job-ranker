"""One collection run: every company feed, then every search, with a log row for each."""

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import partial

import httpx

from jobranker.config import Company, Search
from jobranker.sources import FEEDS, linkedin
from jobranker.sources.base import FetchResult, SourceError
from jobranker.store import Outcome, Store

DEFAULT_MAX_RESULTS = 200
NO_TOKEN = "skipped: APIFY_TOKEN is not set"
LIMIT_REACHED = "skipped: run limit reached"


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class SourceReport:
    """What one company feed or one search did in a run."""

    source: str
    target: str
    fetched: int = 0
    new: int = 0
    changed: int = 0
    duplicate: int = 0
    skipped: int = 0
    error: str | None = None

    def line(self) -> str:
        head = f"{self.source:<10} {self.target}: "
        if self.error is not None:
            return head + self.error
        counts = (
            f"fetched {self.fetched}, new {self.new}, changed {self.changed},"
            f" duplicate {self.duplicate}"
        )
        return head + counts + (f", skipped {self.skipped}" if self.skipped else "")


def _run_source(
    report: SourceReport,
    fetch: Callable[[], FetchResult],
    store: Store,
    now: Callable[[], datetime],
) -> SourceReport:
    """Fetch one source and save its postings. A failure becomes the report's error."""
    try:
        result = fetch()
        counts = dict.fromkeys(Outcome, 0)
        for posting in result.postings:
            counts[store.save(posting, now())] += 1
    except SourceError as error:
        return replace(report, error=error.reason)
    except Exception as error:  # noqa: BLE001 - one broken source must not stop the others
        # Only the class name is kept: the message could hold a token or posting text.
        return replace(report, error=f"internal error: {type(error).__name__}")
    return replace(
        report,
        fetched=len(result.postings),
        new=counts[Outcome.NEW],
        changed=counts[Outcome.CHANGED],
        duplicate=counts[Outcome.DUPLICATE],
        skipped=result.skipped,
    )


def collect(
    companies: Sequence[Company],
    searches: Sequence[Search],
    store: Store,
    client: httpx.Client,
    *,
    token: str | None,
    max_results: int = DEFAULT_MAX_RESULTS,
    actor: str = linkedin.DEFAULT_ACTOR,
    now: Callable[[], datetime] = utc_now,
) -> list[SourceReport]:
    """Collect from every source and return one report per company and per search.

    Company feeds run first, so a posting that a feed and a search both return is stored
    as the feed's posting and the search's copy is linked to it.
    """
    run_id = uuid.uuid4().hex
    started_at = now()
    reports: list[SourceReport] = []

    def finish(report: SourceReport) -> None:
        store.log_run(
            run_id,
            started_at,
            report.source,
            report.target,
            fetched=report.fetched,
            new=report.new,
            changed=report.changed,
            duplicate=report.duplicate,
            skipped=report.skipped,
            error=report.error,
        )
        reports.append(report)

    for company in companies:
        fetch_feed = partial(FEEDS[company.feed], client, company)
        finish(_run_source(SourceReport(company.feed, company.name), fetch_feed, store, now))

    # Every result is billed, so the run limit counts what was asked for, not what came back.
    remaining = max_results
    for search in searches:
        report = SourceReport(linkedin.SOURCE, f"{search.keywords} / {search.location}")
        if token is None:
            finish(replace(report, error=NO_TOKEN))
            continue
        asked = min(search.limit, remaining)
        if asked <= 0:
            finish(replace(report, error=LIMIT_REACHED))
            continue
        remaining -= asked
        fetch_search = partial(
            linkedin.fetch, client, search, token=token, limit=asked, actor=actor
        )
        finish(_run_source(report, fetch_search, store, now))
    return reports
