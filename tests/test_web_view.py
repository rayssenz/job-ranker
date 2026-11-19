from datetime import UTC, datetime, timedelta

import pytest

from jobranker.models import Posting
from jobranker.profile import Levels, Profile
from jobranker.web import view

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
PROFILE = Profile(places=["Lisbon"], levels=Levels(accept=["working student", "junior"]))


def test_short_text_is_not_cut() -> None:
    assert view.excerpt("Build models.") == ("Build models.", False)


def test_text_of_exactly_the_limit_is_not_cut() -> None:
    text = "a" * 280
    assert view.excerpt(text) == (text, False)


def test_long_text_is_cut_at_a_word_within_the_limit() -> None:
    text = "word " * 100
    short, cut = view.excerpt(text)
    assert cut
    assert short == ("word " * 56).strip()
    assert len(short) <= 280


def test_cut_never_splits_a_word() -> None:
    short, cut = view.excerpt("alpha beta gamma delta", limit=13)
    assert (short, cut) == ("alpha beta", True)
    assert view.excerpt("alpha beta gamma delta", limit=10) == ("alpha beta", True)


def test_one_word_longer_than_the_limit_is_cut_at_the_limit() -> None:
    assert view.excerpt("x" * 300) == ("x" * 280, True)


def test_line_breaks_and_runs_of_spaces_become_single_spaces() -> None:
    assert view.excerpt("Build\n\nmodels.   Ship  them.\n") == ("Build models. Ship them.", False)


def test_empty_text_gives_an_empty_excerpt() -> None:
    assert view.excerpt("  \n ") == ("", False)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.test/jobs/1",
        "http://example.test/jobs/1?a=1&b=2#top",
        "HTTPS://Example.test/jobs",
        "https://example.test:8443/x",
    ],
)
def test_web_address_is_a_safe_link(url: str) -> None:
    assert view.safe_link(url) == url


def test_white_space_around_an_address_is_removed() -> None:
    assert view.safe_link("  https://example.test/jobs/1 \n") == "https://example.test/jobs/1"


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        "   javascript:alert(1)",
        "\tjavascript:alert(1)",
        "java\tscript:alert(1)",
        "java\nscript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "file:///etc/passwd",
        "ftp://example.test/file",
        "mailto:someone@example.test",
        "//example.test/jobs/1",
        "/jobs/1",
        "example.test/jobs/1",
        "https://",
        "https:///jobs/1",
        "https:example.test",
        "https:\\\\example.test",
        "http://[bad",
        "https://example.test/a b",
        "https://exa\nmple.test/",
        "https://example.test/\x00",
        "javascript://example.test/%0aalert(1)",
    ],
)
def test_anything_else_is_not_a_link(url: str) -> None:
    assert view.safe_link(url) is None


@pytest.mark.parametrize(
    ("ago", "text"),
    [
        (timedelta(0), "today"),
        (timedelta(hours=23, minutes=59), "today"),
        (timedelta(hours=24), "1 day ago"),
        (timedelta(days=1, hours=23), "1 day ago"),
        (timedelta(days=2), "2 days ago"),
        (timedelta(days=40), "40 days ago"),
        (timedelta(hours=-5), "today"),
    ],
)
def test_age_in_whole_days(ago: timedelta, text: str) -> None:
    assert view.age(NOW - ago, NOW) == text


@pytest.mark.parametrize(
    ("ago", "fresh"),
    [(timedelta(0), True), (timedelta(hours=23), True), (timedelta(hours=24), False)],
)
def test_posting_is_new_for_twenty_four_hours(ago: timedelta, fresh: bool) -> None:
    assert view.is_new(NOW - ago, NOW) is fresh


@pytest.mark.parametrize(
    ("title", "entry"),
    [
        ("Working Student Machine Learning", True),
        ("Junior Data Engineer", True),
        ("JUNIOR data engineer (all genders)", True),
        ("Data Engineer", False),
        ("Senior Data Engineer", False),
        ("Juniorprofessor", False),
        ("Student Assistant", False),
    ],
)
def test_entry_level_titles_hold_an_accepted_level(title: str, entry: bool) -> None:
    assert view.is_entry_level(title, PROFILE) is entry


def test_no_title_is_entry_level_without_accepted_levels() -> None:
    assert not view.is_entry_level("Junior Data Engineer", Profile(places=["Lisbon"]))


POSTING = Posting(
    source="greenhouse",
    board="northwindrobotics",
    posting_id="1",
    company="Northwind Robotics",
    title="Machine Learning Engineer",
    location="Lisbon, Portugal",
    description="Work with harbour cranes.",
)


@pytest.mark.parametrize(
    "query",
    ["", "   ", "machine", "MACHINE learning", "robotics", "lisbon", "engineer northwind", "learn"],
)
def test_query_matches_title_company_or_location(query: str) -> None:
    assert view.matches(POSTING, query)


@pytest.mark.parametrize("query", ["porto", "machine porto", "cranes", "harbour"])
def test_query_with_a_word_that_is_nowhere_does_not_match(query: str) -> None:
    assert not view.matches(POSTING, query)


def test_source_names_for_the_person() -> None:
    assert view.SOURCE_NAMES == {
        "greenhouse": "company page",
        "lever": "company page",
        "ashby": "company page",
        "linkedin": "LinkedIn",
    }
