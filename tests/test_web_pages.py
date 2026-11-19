"""The pages of the dashboard, read side. Every posting here is made up."""

import re
from datetime import UTC, datetime, timedelta
from html import unescape
from importlib import resources
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jobranker.models import Posting
from jobranker.profile import Levels, Profile
from jobranker.rules import RULES_VERSION
from jobranker.screening import apply_rules
from jobranker.store import Decision, Store
from jobranker.web.app import create_app

PORT = 8765
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
PROFILE = Profile(places=["Lisbon", "Porto"], levels=Levels(accept=["working student", "junior"]))
PAGES = ["/", "/applied", "/dismissed", "/runs"]


def posting(number: int, **changes: str) -> Posting:
    fields = {
        "source": "greenhouse",
        "board": "northwindrobotics",
        "posting_id": str(number),
        "company": "Northwind Robotics",
        "title": f"Role {number}",
        "location": "Lisbon",
        "url": f"https://example.test/jobs/{number}",
        "description": "Build models.",
    }
    return Posting.model_validate(fields | changes)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "ranker.db"
    Store(path).close()
    return path


def add(db: Path, *postings: Posting, seen: datetime = NOW - timedelta(days=2)) -> None:
    with Store(db) as store:
        for item in postings:
            store.save(item, seen)
        apply_rules(store, PROFILE, seen)


def decide(db: Path, item: Posting, decision: Decision, when: datetime = NOW) -> None:
    with Store(db) as store:
        stored = store.get(item.source, item.board, item.posting_id)
        assert stored is not None
        assert store.decide(stored.id, decision, when)


def site(db: Path, *, now: datetime = NOW, profile: Profile = PROFILE) -> TestClient:
    app = create_app(db, profile, port=PORT, now=lambda: now)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}")


def page(db: Path, path: str = "/", *, profile: Profile = PROFILE) -> str:
    response = site(db, profile=profile).get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html: str = response.text
    return html


def titles(html: str) -> list[str]:
    return [unescape(t) for t in re.findall(r'<h2 class="card-title">(.*?)</h2>', html, re.S)]


def counts(html: str) -> dict[str, int]:
    found = re.findall(r'href="(/[a-z]*)"[^>]*>[^<]*<span class="count">(\d+)</span>', html)
    return {path: int(number) for path, number in found}


def test_review_tab_lists_the_passing_groups_newest_first(db: Path) -> None:
    add(db, posting(1, title="Old Role"), seen=NOW - timedelta(days=3))
    add(db, posting(2, title="New Role"), seen=NOW - timedelta(days=1))
    add(db, posting(3, title="Elsewhere Role", location="Madrid"), seen=NOW)
    html = page(db)
    assert titles(html) == ["New Role", "Old Role"]
    assert "2 jobs to review" in html
    assert counts(html)["/"] == 2


def test_one_job_is_not_plural(db: Path) -> None:
    add(db, posting(1))
    assert "1 job to review" in page(db)


def test_each_tab_has_its_count_and_its_groups(db: Path) -> None:
    first, second, third = posting(1, title="Open Role"), posting(2, title="Sent Role"), posting(3)
    add(db, first, second, third.model_copy(update={"title": "Dull Role"}))
    decide(db, second, Decision.APPLIED)
    decide(db, third, Decision.DISMISSED)
    for path in PAGES:
        assert counts(page(db, path)) == {"/": 1, "/applied": 1, "/dismissed": 1}
    assert titles(page(db)) == ["Open Role"]
    assert titles(page(db, "/applied")) == ["Sent Role"]
    assert titles(page(db, "/dismissed")) == ["Dull Role"]


def test_the_open_tab_is_marked(db: Path) -> None:
    for path in PAGES:
        marked = re.findall(r'<a class="tab" href="([^"]*)" aria-current="page"', page(db, path))
        assert marked == [path]


def test_card_shows_company_location_source_and_age(db: Path) -> None:
    add(db, posting(1), seen=NOW - timedelta(days=2))
    add(db, posting(2, source="linkedin", board="", company="Bluefjord Labs", location="Porto"))
    html = page(db)
    for text in ("Northwind Robotics", "Lisbon", "company page, 2 days ago"):
        assert text in html
    for text in ("Bluefjord Labs", "Porto", "LinkedIn, 2 days ago"):
        assert text in html


def test_posting_without_a_location_shows_no_empty_field(db: Path) -> None:
    add(db, posting(1, location=""))
    assert "<span></span>" not in page(db)


def test_posting_first_seen_in_the_last_day_has_a_marked_edge(db: Path) -> None:
    add(db, posting(1, title="Old Role"), seen=NOW - timedelta(hours=25))
    add(db, posting(2, title="New Role"), seen=NOW - timedelta(hours=2))
    html = page(db)
    assert len(re.findall(r'<article class="card fresh"', html)) == 1
    assert len(re.findall(r'<article class="card"', html)) == 1
    assert html.index('class="card fresh"') < html.index("New Role") < html.index('class="card"')
    assert "company page, today" in html


def test_linked_group_is_shown_once(db: Path) -> None:
    add(db, posting(1, title="ML Engineer"))
    add(db, posting(900, source="linkedin", board="", title="ML Engineer"))
    html = page(db)
    assert titles(html) == ["ML Engineer"]
    assert counts(html)["/"] == 1


def entry_level_postings(db: Path) -> None:
    add(db, posting(1, title="Data Engineer"), seen=NOW - timedelta(days=4))
    add(db, posting(2, title="Junior Data Engineer"), seen=NOW - timedelta(days=3))
    add(db, posting(3, title="Working Student ML", location="Porto"), seen=NOW - timedelta(days=2))
    add(
        db, posting(4, title="Senior Platform Lead", location="Porto"), seen=NOW - timedelta(days=1)
    )


def test_switch_keeps_the_titles_with_an_accepted_level(db: Path) -> None:
    entry_level_postings(db)
    html = page(db, "/?entry=1")
    assert titles(html) == ["Working Student ML", "Junior Data Engineer"]
    assert re.search(r'<input[^>]*name="entry"[^>]*checked', html)
    # The tab still counts everything there is to review.
    assert counts(html)["/"] == 4
    assert "Showing 2 of 4" in html


def test_switch_is_off_without_its_value(db: Path) -> None:
    entry_level_postings(db)
    for path in ("/", "/?entry=0", "/?entry=yes", "/?entry="):
        html = page(db, path)
        assert len(titles(html)) == 4
        assert not re.search(r'<input[^>]*name="entry"[^>]*checked', html)


def test_search_keeps_the_cards_that_hold_the_text(db: Path) -> None:
    entry_level_postings(db)
    assert titles(page(db, "/?q=porto")) == ["Senior Platform Lead", "Working Student ML"]
    assert titles(page(db, "/?q=DATA+engineer")) == ["Junior Data Engineer", "Data Engineer"]
    assert titles(page(db, "/?q=northwind")) == [
        "Senior Platform Lead",
        "Working Student ML",
        "Junior Data Engineer",
        "Data Engineer",
    ]
    assert 'value="porto"' in page(db, "/?q=porto")


def test_switch_and_search_can_be_combined(db: Path) -> None:
    entry_level_postings(db)
    html = page(db, "/?entry=1&q=porto")
    assert titles(html) == ["Working Student ML"]
    assert 'value="porto"' in html
    assert re.search(r'<input[^>]*name="entry"[^>]*checked', html)


def test_search_without_a_match_says_how_to_go_on(db: Path) -> None:
    entry_level_postings(db)
    html = page(db, "/?q=zebra")
    assert titles(html) == []
    assert "No job matches" in html
    assert 'href="/"' in html


def test_very_long_search_text_is_cut(db: Path) -> None:
    add(db, posting(1))
    html = page(db, "/?q=" + "a" * 500)
    assert "a" * 101 not in html


def many(db: Path, number: int) -> None:
    with Store(db) as store:
        for n in range(number):
            title = f"Junior Role {n}" if n % 2 else f"Role {n}"
            store.save(posting(n, title=title), NOW - timedelta(days=5) + timedelta(minutes=n))
        apply_rules(store, PROFILE, NOW)


def test_fifty_cards_per_page_with_a_link_to_the_next(db: Path) -> None:
    many(db, 120)
    first = page(db)
    assert titles(first) == [
        f"Junior Role {n}" if n % 2 else f"Role {n}" for n in range(119, 69, -1)
    ]
    assert 'href="/?page=2"' in first
    assert "Page 1 of 3" in first
    assert "Previous page" not in first
    last = page(db, "/?page=3")
    assert len(titles(last)) == 20
    assert "Next page" not in last
    assert 'href="/?page=2"' in last
    assert counts(last)["/"] == 120


def test_page_links_keep_the_switch_and_the_search(db: Path) -> None:
    many(db, 120)
    html = page(db, "/?entry=1&q=junior+role")
    assert len(titles(html)) == 50
    assert 'href="/?entry=1&amp;q=junior+role&amp;page=2"' in html
    assert "Showing 60 of 120" in html
    assert len(titles(page(db, "/?entry=1&q=junior+role&page=2"))) == 10


@pytest.mark.parametrize("value", ["abc", "0", "-3", "", "1.5", "99999999999999999999"])
def test_page_value_that_is_no_page_shows_a_real_page(db: Path, value: str) -> None:
    many(db, 60)
    html = page(db, f"/?page={value}")
    assert len(titles(html)) in (50, 10)
    assert "of 2" in html


def test_single_page_has_no_page_links(db: Path) -> None:
    add(db, posting(1))
    html = page(db)
    assert "Next page" not in html and "Page 1" not in html


LONG = "Tune the harbour crane models. " * 20


def test_long_description_is_cut_at_a_word_and_the_full_text_is_there(db: Path) -> None:
    add(db, posting(1, description=LONG))
    html = page(db)
    shown = re.search(r'<p class="excerpt">(.*?)</p>', html, re.S)
    assert shown is not None
    text = unescape(shown.group(1)).strip().removesuffix("…").strip()
    assert len(text) <= 280
    assert LONG.startswith(text) and LONG[len(text)] == " "
    assert "Show full text" in html
    assert " ".join(LONG.split()) in " ".join(html.split())


def test_short_description_needs_no_full_text(db: Path) -> None:
    add(db, posting(1, description="Build models."))
    html = page(db)
    assert "Build models." in html
    assert "Show full text" not in html


def test_applied_tab_shows_a_stamp_with_the_date_newest_mark_first(db: Path) -> None:
    first, second, third = (
        posting(1, title="First Sent"),
        posting(2, title="Second Sent"),
        posting(3),
    )
    add(db, first, second, third)
    decide(db, second, Decision.APPLIED, datetime(2026, 11, 17, 12, 0, tzinfo=UTC))
    decide(db, first, Decision.APPLIED, datetime(2026, 11, 18, 12, 0, tzinfo=UTC))
    decide(db, third, Decision.DISMISSED, datetime(2026, 11, 16, 12, 0, tzinfo=UTC))
    html = page(db, "/applied")
    assert titles(html) == ["First Sent", "Second Sent"]
    assert re.findall(r'<p class="stamp">\s*(.*?)\s*</p>', html) == [
        "Applied 18 Nov",
        "Applied 17 Nov",
    ]
    assert "2 applications" in html
    dismissed = page(db, "/dismissed")
    assert 'class="stamp"' not in dismissed
    assert "1 job not for me" in dismissed
    assert 'class="stamp"' not in page(db)


def test_decided_group_stays_in_its_tab_after_a_profile_change(db: Path) -> None:
    sent = posting(1, title="Sent Role")
    add(db, sent, posting(2, title="Open Role"))
    decide(db, sent, Decision.APPLIED)
    other = Profile(places=["Madrid"])
    with Store(db) as store:
        apply_rules(store, other, NOW)
        assert store.review_groups(other.digest, RULES_VERSION) == []
    assert titles(page(db, "/applied", profile=other)) == ["Sent Role"]
    assert counts(page(db, profile=other)) == {"/": 0, "/applied": 1, "/dismissed": 0}


def test_empty_database_says_to_collect(db: Path) -> None:
    html = page(db)
    assert "0 jobs to review" in html
    assert "No jobs yet" in html and "jobrank collect" in html


def test_review_tab_with_everything_decided_says_so(db: Path) -> None:
    add(db, posting(1))
    decide(db, posting(1), Decision.DISMISSED)
    html = page(db)
    assert "Everything is reviewed" in html and "jobrank collect" in html


@pytest.mark.parametrize(
    ("path", "sentence"),
    [
        ("/applied", "No applications yet"),
        ("/dismissed", "Nothing marked not for me"),
        ("/runs", "No runs yet"),
    ],
)
def test_empty_tab_says_what_to_do_next(db: Path, path: str, sentence: str) -> None:
    add(db, posting(1))
    assert sentence in page(db, path)


HOSTILE = {
    "title": "<script>alert(1)</script> Engineer",
    "company": '"><img src=x onerror=alert(2)>',
    "location": "Lisbon {{ 7 * 7 }} <b>bold</b>",
    "description": "<iframe src='//evil.test'></iframe> {% raw %} {{ config }} \" ' </p></article>"
    + " word" * 100,
}


@pytest.mark.parametrize("decision", [None, Decision.APPLIED, Decision.DISMISSED])
def test_markup_in_a_posting_is_shown_as_text(db: Path, decision: Decision | None) -> None:
    hostile = posting(1, **HOSTILE)
    add(db, hostile)
    if decision is not None:
        decide(db, hostile, decision)
    path = {None: "/", Decision.APPLIED: "/applied", Decision.DISMISSED: "/dismissed"}[decision]
    html = page(db, path)
    assert titles(html) == [HOSTILE["title"]]
    for raw in ("<script>alert", "<img", "<iframe", "<b>bold", "onerror=alert(2)>"):
        assert raw not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt; Engineer" in html
    assert "&lt;img src=x onerror=alert(2)&gt;" in html
    assert "{{ 7 * 7 }}" in html
    assert "{% raw %} {{ config }}" in html
    assert "&lt;iframe src=&#39;//evil.test&#39;&gt;" in html
    # The card is still closed by the template, once.
    assert html.count("</article>") == 1


def test_markup_in_the_search_text_is_shown_as_text(db: Path) -> None:
    add(db, posting(1))
    html = site(db).get("/", params={"q": '"><script>alert(1)</script>'}).text
    assert "<script>alert" not in html
    assert "&#34;&gt;&lt;script&gt;" in html


def test_markup_in_a_run_error_is_shown_as_text(db: Path) -> None:
    with Store(db) as store:
        store.log_run("run1", NOW, "lever", "<b>Bluefjord</b>", error="<script>alert(1)</script>")
    html = page(db, "/runs")
    assert "<script>alert" not in html and "<b>Bluefjord" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_web_link_opens_in_a_new_tab_without_a_referrer(db: Path) -> None:
    add(db, posting(1, url="https://example.test/jobs/1?a=1&b=2"))
    html = page(db)
    link = re.search(r"<a [^>]*>\s*Open posting\s*</a>", html)
    assert link is not None
    assert 'href="https://example.test/jobs/1?a=1&amp;b=2"' in link.group(0)
    assert 'target="_blank"' in link.group(0)
    assert 'rel="noopener noreferrer"' in link.group(0)


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        "   javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "https:///jobs/1",
        "//example.test/jobs/1",
        "",
    ],
)
@pytest.mark.parametrize("decided", [False, True])
def test_other_address_is_not_shown_as_a_link(db: Path, url: str, decided: bool) -> None:
    add(db, posting(1, url=url))
    if decided:
        decide(db, posting(1), Decision.APPLIED)
    html = page(db, "/applied" if decided else "/")
    assert titles(html) == ["Role 1"]
    assert "Open posting" not in html
    assert "javascript:" not in html.lower() and "data:" not in html.lower()
    assert "target=" not in html


def log_runs(db: Path, number: int) -> None:
    with Store(db) as store:
        for n in range(1, number + 1):
            started = datetime(2026, 11, n, 12, 0, tzinfo=UTC)
            store.log_run(f"run{n}", started, "greenhouse", "Northwind Robotics", fetched=9, new=n)
            store.log_run(f"run{n}", started, "ashby", "Tessellate Systems", fetched=4, new=1)
            if n in (3, number):
                store.log_run(
                    f"run{n}", started, "lever", "Bluefjord Labs", error=f"HTTP 50{n % 10}"
                )


def test_runs_tab_shows_the_last_ten_runs_newest_first(db: Path) -> None:
    log_runs(db, 12)
    html = page(db, "/runs")
    rows = re.findall(
        r"<tr>\s*<td>(.*?)</td>\s*<td>(\d+)</td>\s*<td[^>]*>(\d+)</td>\s*<td>(\d+)</td>", html
    )
    assert [(int(a), int(b), int(c)) for _, a, b, c in rows] == [
        (3, 1, 13),
        *[(2, 0, n + 1) for n in range(11, 3, -1)],
        (3, 1, 4),
    ]
    assert rows[0][0].startswith("12 Nov 2026")
    # Only ten runs are shown, so a count on this tab would look like a total.
    assert "/runs" not in counts(html)
    assert "Last 10 runs" in html


def test_runs_tab_names_the_sources_the_latest_run_did_not_collect(db: Path) -> None:
    log_runs(db, 12)
    html = page(db, "/runs")
    assert "Bluefjord Labs" in html and "HTTP 502" in html
    # The failure of an older run is not listed.
    assert "HTTP 503" not in html


def test_runs_tab_says_when_the_latest_run_collected_everything(db: Path) -> None:
    log_runs(db, 5)
    with Store(db) as store:
        store.log_run("run6", NOW, "greenhouse", "Northwind Robotics", fetched=9, new=0)
    html = page(db, "/runs")
    assert "Every source was collected" in html
    assert "HTTP 50" not in html


def test_review_tab_has_one_line_on_the_latest_run(db: Path) -> None:
    add(db, posting(1))
    log_runs(db, 12)
    html = " ".join(page(db).split())
    assert "Last run on 12 Nov" in html
    assert "3 sources" in html and "1 not collected" in html and "13 new" in html


def test_review_tab_without_a_run_has_no_run_line(db: Path) -> None:
    add(db, posting(1))
    assert "Last run" not in page(db)


def test_pages_name_no_other_machine_and_hold_no_inline_code(db: Path) -> None:
    add(db, posting(1, url=""), posting(2, url="", description=LONG))
    decide(db, posting(2), Decision.APPLIED)
    log_runs(db, 3)
    for path in ["/", "/?entry=1&q=role", *PAGES[1:]]:
        html = page(db, path)
        for forbidden in ("http:", "https:", 'src="//', 'href="//', "<style", "style=", "<script>"):
            assert forbidden not in html, (path, forbidden)
        for address in re.findall(r'(?:href|src|action)="([^"]*)"', html):
            assert address.startswith("/") and not address.startswith("//"), address


def test_page_loads_its_styles_from_the_package(db: Path) -> None:
    html = page(db)
    assert '<link rel="stylesheet" href="/static/dashboard.css">' in html
    assert '<html lang="en">' in html
    assert '<meta name="viewport"' in html


def test_styles_are_served_and_name_no_other_machine(db: Path) -> None:
    response = site(db).get("/static/dashboard.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    css = response.text
    assert "http" not in css and "//" not in css and "@import" not in css
    fonts = re.findall(r'url\("([^"]*)"\)', css)
    assert sorted(fonts) == ["fonts/bricolage-grotesque.woff2", "fonts/instrument-sans.woff2"]
    assert "Bricolage Grotesque" in css and "Instrument Sans" in css


@pytest.mark.parametrize("name", ["bricolage-grotesque", "instrument-sans"])
def test_fonts_ship_with_their_licence_texts(db: Path, name: str) -> None:
    client = site(db)
    font = client.get(f"/static/fonts/{name}.woff2")
    assert font.status_code == 200
    assert font.content[:4] == b"wOF2"
    licence = resources.files("jobranker.web") / "static" / "fonts" / f"{name}-OFL.txt"
    assert "SIL Open Font License" in licence.read_text(encoding="utf-8")


def test_templates_are_found_through_the_package() -> None:
    folder = resources.files("jobranker.web") / "templates"
    assert {"base.html", "cards.html", "runs.html"} <= {item.name for item in folder.iterdir()}


@pytest.mark.parametrize(
    "path", ["/docs", "/redoc", "/openapi.json", "/nothing", "/static/../app.py"]
)
def test_no_automatic_api_pages_and_no_other_path(db: Path, path: str) -> None:
    assert site(db).get(path).status_code == 404


def test_a_page_request_stores_nothing(db: Path) -> None:
    add(db, posting(1))
    with Store(db) as store:
        before = store.dump()
    for path in PAGES:
        page(db, path)
    with Store(db) as store:
        assert store.dump() == before


def test_postings_collected_while_the_dashboard_runs_appear_after_a_reload(db: Path) -> None:
    add(db, posting(1, title="Old Role"))
    client = site(db)
    assert titles(client.get("/").text) == ["Old Role"]
    # A collection run stores postings and applies no rules.
    with Store(db) as store:
        store.save(posting(2, title="New Role"), NOW)
        store.save(posting(3, title="Elsewhere Role", location="Madrid"), NOW)
        store.save(posting(1, title="Old Role", description="Build better models."), NOW)
    html = client.get("/").text
    assert titles(html) == ["New Role", "Old Role"]
    assert counts(html)["/"] == 2
    assert counts(client.get("/applied").text)["/"] == 2


def test_review_tab_says_when_no_job_passed_the_rules(db: Path) -> None:
    add(db, posting(1, location="Madrid"), posting(2, location="Madrid"))
    html = page(db)
    assert "0 jobs to review" in html
    assert "No job passed the rules" in html and "profile.yaml" in html
    assert "Everything is reviewed" not in html


def test_rules_are_applied_again_only_when_something_was_collected(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    add(db, posting(1))
    calls: list[int] = []

    def counting(store: Store, profile: Profile, now: datetime) -> int:
        calls.append(1)
        return apply_rules(store, profile, now)

    monkeypatch.setattr("jobranker.web.app.apply_rules", counting)
    client = site(db)
    for path in PAGES:
        client.get(path)
    # Once at the first request, in case the application was started without a rule run.
    assert len(calls) == 1
    with Store(db) as store:
        store.save(posting(2, title="New Role"), NOW)
    assert titles(client.get("/").text) == ["New Role", "Role 1"]
    client.get("/applied")
    assert len(calls) == 2
