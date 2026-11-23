import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from support import (
    ASHBY,
    GREENHOUSE,
    LEVER,
    PERSONIO,
    SEARCH,
    TOKEN,
    Recorder,
    Route,
    routes,
    sample,
    sample_text,
)

import jobranker.sources
from jobranker.collect import SourceReport, collect
from jobranker.config import Company, Search
from jobranker.models import Remote
from jobranker.sources.base import FetchResult
from jobranker.store import Store

COMPANIES = [GREENHOUSE, LEVER, ASHBY]
SECOND_SEARCH = Search(keywords="data engineer", location="Portugal", posted_within="week")
SEARCHES = [SEARCH, SECOND_SEARCH]
NOW = datetime(2026, 11, 19, 8, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "ranker.db")


def run(
    store: Store,
    recorder: Recorder,
    *,
    companies: list[Company] | None = None,
    searches: list[Search] | None = None,
    token: str | None = TOKEN,
    max_results: int = 200,
) -> list[SourceReport]:
    return collect(
        COMPANIES if companies is None else companies,
        SEARCHES if searches is None else searches,
        store,
        recorder.client,
        token=token,
        max_results=max_results,
        now=lambda: NOW,
    )


def test_stores_every_posting_from_all_four_sources(store: Store) -> None:
    reports = run(store, routes())
    assert [(r.source, r.target) for r in reports] == [
        ("greenhouse", "Northwind Robotics"),
        ("lever", "Bluefjord Labs"),
        ("ashby", "Tessellate Systems"),
        ("linkedin", "machine learning engineer / Lisbon"),
        ("linkedin", "data engineer / Portugal"),
    ]
    assert [r.error for r in reports] == [None] * 5
    assert [r.fetched for r in reports] == [3, 3, 3, 3, 3]
    assert [r.new for r in reports] == [3, 3, 3, 2, 0]
    assert store.count() == 12

    greenhouse = store.get("greenhouse", "northwindrobotics", "1001")
    lever = store.get("lever", "bluefjord", "0a000000-0000-4000-8000-000000000002")
    ashby = store.get("ashby", "tessellate", "0b000000-0000-4000-8000-000000000003")
    linkedin = store.get("linkedin", "", "9000000002")
    assert greenhouse and lever and ashby and linkedin
    assert greenhouse.posting.description == "Build & run perception models.\nPython\nPyTorch"
    assert (lever.posting.title, lever.posting.remote) == ("Analytics Engineer", Remote.YES)
    assert (ashby.posting.location, ashby.posting.remote) == ("Graz", Remote.NO)
    assert (linkedin.posting.company, linkedin.posting.title) == ("Quillmark", "Research Engineer")
    assert linkedin.first_seen == NOW


def test_second_run_reports_nothing_new(store: Store) -> None:
    run(store, routes())
    reports = run(store, routes())
    assert [(r.new, r.changed, r.duplicate) for r in reports] == [(0, 0, 0)] * 5
    assert [r.fetched for r in reports] == [3, 3, 3, 3, 3]
    assert store.count() == 12


def test_changed_posting_is_counted_as_changed(store: Store) -> None:
    run(store, routes())
    edited = copy.deepcopy(sample("ashby"))
    edited["jobs"][0]["descriptionPlain"] = "Build the new tiling service."
    reports = run(store, routes(ashby=lambda r: httpx.Response(200, json=edited)))
    ashby = reports[2]
    assert (ashby.new, ashby.changed, ashby.duplicate) == (0, 1, 0)
    stored = store.get("ashby", "tessellate", "0b000000-0000-4000-8000-000000000001")
    assert stored is not None
    assert len(store.versions(stored.id)) == 2


def test_linkedin_copy_of_feed_posting_is_duplicate(store: Store) -> None:
    reports = run(store, routes())
    assert reports[3].duplicate == 1
    original = store.get("greenhouse", "northwindrobotics", "1001")
    copy_row = store.get("linkedin", "", "9000000001")
    assert original and copy_row
    assert copy_row.duplicate_of == original.id


def test_same_result_in_two_searches_is_stored_once(store: Store) -> None:
    reports = run(store, routes(), companies=[])
    first, second = reports
    assert (first.fetched, first.new) == (3, 3)
    assert (second.fetched, second.new, second.changed, second.duplicate) == (3, 0, 0, 0)
    assert store.count() == 3


def _timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("slow", request=request)


@pytest.mark.parametrize(
    ("route", "reason"),
    [
        (lambda r: httpx.Response(404, json={}), "HTTP 404"),
        (_timeout, "timeout"),
        (lambda r: httpx.Response(200, text="<html>"), "not JSON"),
        (lambda r: httpx.Response(200, json={"unexpected": True}), "unexpected shape"),
    ],
)
def test_failing_feed_does_not_stop_the_run(store: Store, route: Route, reason: str) -> None:
    reports = run(store, routes(lever=route))
    assert reports[1].error == reason
    assert [r.error for r in reports if r.source != "lever"] == [None] * 4
    assert store.count() == 9
    logged = store.runs()
    assert len(logged) == 5
    assert len({row["run_id"] for row in logged}) == 1
    assert [row["error"] for row in logged] == [None, reason, None, None, None]
    assert logged[1]["target"] == "Bluefjord Labs"
    assert (logged[0]["fetched"], logged[0]["new"]) == (3, 3)


def test_searches_are_skipped_without_token(store: Store) -> None:
    recorder = routes()
    reports = run(store, recorder, token=None)
    assert [r.error for r in reports[3:]] == ["skipped: APIFY_TOKEN is not set"] * 2
    assert all(request.url.host != "api.apify.com" for request in recorder.requests)
    assert store.count() == 9


def asked_limits(recorder: Recorder) -> list[int]:
    return [
        json.loads(request.content)["limit"]
        for request in recorder.requests
        if request.url.host == "api.apify.com"
    ]


def test_run_limit_is_shared_in_order(store: Store) -> None:
    recorder = routes()
    run(store, recorder, companies=[], max_results=60)
    assert asked_limits(recorder) == [50, 10]


def test_search_after_the_limit_is_skipped(store: Store) -> None:
    recorder = routes()
    reports = run(store, recorder, companies=[], max_results=50)
    assert asked_limits(recorder) == [50]
    assert reports[1].error == "skipped: run limit reached"


@pytest.mark.parametrize("max_results", [1, 49, 50, 51, 99, 100, 500])
def test_total_asked_never_exceeds_the_run_limit(store: Store, max_results: int) -> None:
    recorder = routes()
    run(store, recorder, companies=[], max_results=max_results)
    assert sum(asked_limits(recorder)) <= max_results


def test_failed_search_still_uses_its_share_of_the_limit(store: Store) -> None:
    calls = iter([httpx.Response(402, json={}), httpx.Response(201, json=sample("linkedin"))])
    recorder = routes(apify=lambda r: next(calls))
    reports = run(store, recorder, companies=[], max_results=60)
    assert asked_limits(recorder) == [50, 10]
    assert reports[0].error == "HTTP 402"
    assert reports[1].error is None


def test_token_is_not_written_anywhere(store: Store) -> None:
    calls = iter(
        [
            httpx.Response(401, json={"error": {"message": f"bad token {TOKEN}"}}),
            httpx.Response(201, json=sample("linkedin")),
        ]
    )
    reports = run(store, routes(apify=lambda r: next(calls)))
    assert reports[3].error == "HTTP 401"
    assert all(TOKEN not in report.line() for report in reports)
    assert TOKEN not in store.dump()


def test_recruiter_fields_are_not_stored(store: Store) -> None:
    run(store, routes())
    assert "ecruiter" not in store.dump()


def test_unexpected_exception_is_contained(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(client: httpx.Client, company: Company) -> FetchResult:
        raise ValueError(f"detail with {TOKEN}")

    monkeypatch.setitem(jobranker.sources.FEEDS, "greenhouse", broken)
    reports = run(store, routes())
    assert reports[0].error == "internal error: ValueError"
    assert reports[1].error is None
    assert store.count() == 9


def test_skipped_postings_are_reported(store: Store) -> None:
    body: Any = copy.deepcopy(sample("greenhouse"))
    del body["jobs"][0]["title"]
    reports = run(store, routes(greenhouse=lambda r: httpx.Response(200, json=body)))
    assert (reports[0].fetched, reports[0].skipped, reports[0].new) == (2, 1, 2)
    assert store.runs()[0]["skipped"] == 1


def test_report_lines() -> None:
    ok = SourceReport("greenhouse", "Northwind Robotics", fetched=3, new=2, changed=1)
    assert ok.line() == "greenhouse Northwind Robotics: fetched 3, new 2, changed 1, duplicate 0"
    with_skipped = SourceReport("lever", "Bluefjord Labs", fetched=1, new=1, skipped=2)
    assert with_skipped.line().endswith("duplicate 0, skipped 2")
    failed = SourceReport("ashby", "Tessellate Systems", error="HTTP 404")
    assert failed.line() == "ashby      Tessellate Systems: HTTP 404"


def test_posting_that_cannot_be_saved_does_not_stop_the_rest(store: Store) -> None:
    broken = copy.deepcopy(sample("greenhouse"))
    # A lone surrogate, as left by a cut-off emoji, cannot be written to the database.
    broken["jobs"][1]["content"] = "bad \ud83d end"
    body = json.dumps(broken).encode()
    reports = run(
        store,
        routes(greenhouse=lambda r: httpx.Response(200, content=body)),
        companies=[GREENHOUSE],
        searches=[],
    )
    report = reports[0]
    assert report.error is None
    assert (report.fetched, report.new, report.skipped) == (3, 2, 1)
    assert store.count() == 2
    assert [(row["new"], row["skipped"], row["error"]) for row in store.runs()] == [(2, 1, None)]


def test_callbacks_are_called_around_every_source(store: Store) -> None:
    events: list[tuple[str, str, str | None]] = []
    recorder = routes()
    reports = collect(
        [GREENHOUSE, LEVER],
        SEARCHES,
        store,
        recorder.client,
        token=TOKEN,
        max_results=50,
        now=lambda: NOW,
        on_start=lambda report: events.append(("start", report.target, None)),
        on_finish=lambda report: events.append(("finish", report.target, report.error)),
    )
    assert events == [
        ("start", "Northwind Robotics", None),
        ("finish", "Northwind Robotics", None),
        ("start", "Bluefjord Labs", None),
        ("finish", "Bluefjord Labs", None),
        ("start", "machine learning engineer / Lisbon", None),
        ("finish", "machine learning engineer / Lisbon", None),
        ("start", "data engineer / Portugal", None),
        ("finish", "data engineer / Portugal", "skipped: run limit reached"),
    ]
    assert len(reports) == 4


def test_finish_callback_runs_after_the_log_row_is_written(store: Store) -> None:
    rows_seen: list[int] = []
    collect(
        [GREENHOUSE, LEVER],
        [],
        store,
        routes().client,
        token=None,
        now=lambda: NOW,
        on_finish=lambda report: rows_seen.append(len(store.runs())),
    )
    assert rows_seen == [1, 2]


def test_collects_personio_company(store: Store) -> None:
    (report,) = run(store, routes(), companies=[PERSONIO], searches=[])
    assert (report.source, report.target, report.error) == ("personio", "Larkspur Analytics", None)
    assert (report.fetched, report.new, report.skipped) == (2, 2, 1)
    stored = store.get("personio", "larkspur", "102")
    assert stored and stored.posting.remote == Remote.YES


def test_unknown_personio_name_fails_alone(store: Store) -> None:
    missing = routes(personio=lambda r: httpx.Response(404, text="not found"))
    reports = run(store, missing, companies=[PERSONIO, ASHBY], searches=[])
    assert [(r.source, r.error) for r in reports] == [("personio", "HTTP 404"), ("ashby", None)]
    assert reports[1].new == 3


def test_personio_passing_error_keeps_stored_description(store: Store) -> None:
    run(store, routes(), companies=[PERSONIO], searches=[])

    def english_down(request: httpx.Request) -> httpx.Response:
        if request.url.params["language"] == "en":
            return httpx.Response(503)
        return httpx.Response(200, text=sample_text("personio_de.xml"))

    (report,) = run(store, routes(personio=english_down), companies=[PERSONIO], searches=[])
    assert report.error == "HTTP 503"
    stored = store.get("personio", "larkspur", "102")
    assert stored and stored.posting.description.startswith("About the role")
