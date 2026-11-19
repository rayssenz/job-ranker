import pytest

from jobranker.models import Posting, Remote
from jobranker.profile import Profile
from jobranker.rules import RULES_VERSION, Reason, check

PROFILE = Profile.model_validate(
    {
        "places": ["Lisbon", "Porto"],
        "remote": {"accept": True, "places": ["Portugal", "Europe"]},
        "levels": {
            "accept": ["junior", "intern", "working student"],
            "reject": ["senior", "lead", "head"],
        },
        "languages": ["English", "Portuguese"],
        "avoid": ["gambling", "night shift"],
    }
)


def posting(**changes: object) -> Posting:
    fields: dict[str, object] = {
        "source": "greenhouse",
        "board": "northwindrobotics",
        "posting_id": "1",
        "company": "Northwind Robotics",
        "title": "Data Engineer",
        "location": "Lisbon",
        "description": "Build pipelines.",
    }
    return Posting.model_validate(fields | changes)


def with_profile(**changes: object) -> Profile:
    return Profile.model_validate(PROFILE.model_dump() | changes)


def test_rules_have_a_version() -> None:
    assert RULES_VERSION >= 1


def test_posting_that_fits_passes() -> None:
    assert check(posting(), PROFILE) == ()


@pytest.mark.parametrize(
    "location",
    [
        "Lisbon",
        "lisbon, Portugal",
        "Madrid - Lisbon",
        "Madrid; Porto",
        "Lisbon/Remote",
        "Lisbon Office",
        "HQ Lisbon - Main Street 1",
        "",
    ],
)
def test_accepted_place_anywhere_in_the_location_passes(location: str) -> None:
    assert check(posting(location=location), PROFILE) == ()


@pytest.mark.parametrize("location", ["Madrid", "Lisbonne", "Portobello, UK", "Remote"])
def test_other_place_is_dropped(location: str) -> None:
    assert check(posting(location=location), PROFILE) == (Reason.PLACE,)


@pytest.mark.parametrize(
    ("location", "remote", "passes"),
    [
        ("Remote - Europe", Remote.YES, True),
        ("Remote, Portugal", Remote.YES, True),
        ("Remote - United States", Remote.YES, False),
        ("Remote", Remote.YES, False),
        # The word in the location marks a posting as remote when the field does not.
        ("Remote - Europe", Remote.UNKNOWN, True),
        ("Remote Portugal", Remote.UNKNOWN, True),
        ("Madrid; Remote, Portugal", Remote.NO, True),
        ("Remote - United States", Remote.UNKNOWN, False),
        ("Europe", Remote.UNKNOWN, False),
        ("Remotely Operated Vehicles, Europe", Remote.UNKNOWN, False),
    ],
)
def test_remote_posting_needs_an_accepted_remote_place(
    location: str, remote: Remote, passes: bool
) -> None:
    result = check(posting(location=location, remote=remote), PROFILE)
    assert (result == ()) is passes


def test_remote_posting_anywhere_passes_when_no_remote_place_is_listed() -> None:
    profile = with_profile(remote={"accept": True, "places": []})
    assert check(posting(location="Remote - United States", remote=Remote.YES), profile) == ()


def test_remote_posting_is_dropped_when_remote_is_not_accepted() -> None:
    profile = with_profile(remote={"accept": False, "places": []})
    result = check(posting(location="Remote - Europe", remote=Remote.YES), profile)
    assert result == (Reason.PLACE,)


@pytest.mark.parametrize(
    ("title", "passes"),
    [
        ("Senior Data Engineer", False),
        ("Lead Engineer", False),
        ("Head of Data", False),
        ("Data Engineer", True),
        ("Junior Data Engineer", True),
        ("(Junior) Engineer, reports to Head of Data", True),
        ("Working Student Data Engineering", True),
        ("Internal Tools Engineer", True),
        ("Leadership Program Engineer", True),
        ("Engineer - Headless Commerce", True),
    ],
)
def test_level_rule(title: str, passes: bool) -> None:
    result = check(posting(title=title), PROFILE)
    assert result == (() if passes else (Reason.LEVEL,))


@pytest.mark.parametrize(
    ("title", "passes"),
    [
        ("Support Engineer - Dutch Speaking", False),
        ("Support Engineer (German speaker)", False),
        ("Support Engineer, French speakers welcome", False),
        ("Deutschsprachiger Support Engineer", False),
        ("Support Engineer, niederländischsprachig", False),
        ("Support Engineer - English Speaking", True),
        ("Support Engineer (Portuguese speaker)", True),
        ("Dutch Market Engineer", True),
        ("Speaking Coach", True),
    ],
)
def test_language_rule_reads_the_title(title: str, passes: bool) -> None:
    result = check(posting(title=title), PROFILE)
    assert result == (() if passes else (Reason.LANGUAGE,))


def test_language_in_the_description_alone_does_not_drop() -> None:
    result = check(posting(description="You are a fluent Dutch speaker. Dutch speaking."), PROFILE)
    assert result == ()


def test_profile_languages_can_be_written_in_german() -> None:
    profile = with_profile(languages=["Englisch", "Deutsch"])
    assert check(posting(title="Engineer - German Speaking"), profile) == ()
    assert check(posting(title="Engineer - Dutch Speaking"), profile) == (Reason.LANGUAGE,)


@pytest.mark.parametrize(
    "changes",
    [
        {"company": "Lucky Gambling Ltd"},
        {"title": "Data Engineer, Gambling Platform"},
        {"title": "Data Engineer (Night Shift)"},
    ],
)
def test_avoid_word_in_company_or_title_drops(changes: dict[str, object]) -> None:
    assert check(posting(**changes), PROFILE) == (Reason.AVOID,)


def test_avoid_word_in_the_description_alone_does_not_drop() -> None:
    assert check(posting(description="Not a gambling company."), PROFILE) == ()


def test_title_rule_is_off_when_the_list_is_empty() -> None:
    assert check(posting(title="Barista"), PROFILE) == ()


def test_title_rule_needs_one_of_the_words() -> None:
    profile = with_profile(title_words=["engineer", "machine learning"])
    assert check(posting(title="Barista"), profile) == (Reason.TITLE,)
    assert check(posting(title="Data Engineer"), profile) == ()
    assert check(posting(title="Machine Learning Researcher"), profile) == ()
    assert check(posting(title="Engineering Manager"), profile) == (Reason.TITLE,)


def test_every_failing_rule_is_reported_in_a_fixed_order() -> None:
    profile = with_profile(title_words=["engineer"])
    bad = posting(
        company="Lucky Gambling Ltd", title="Senior Croupier - Dutch Speaking", location="Madrid"
    )
    assert check(bad, profile) == (
        Reason.PLACE,
        Reason.LEVEL,
        Reason.LANGUAGE,
        Reason.AVOID,
        Reason.TITLE,
    )


def test_reason_codes_are_fixed_words() -> None:
    assert [reason.value for reason in Reason] == ["place", "level", "language", "avoid", "title"]


@pytest.mark.parametrize(
    ("title", "passes"),
    [
        # A list of languages is a choice: one known language is enough.
        ("Support Engineer (German/French/English Speaking)", True),
        ("Support Engineer - French or English Speaking", True),
        ("Support Engineer - Dutch oder Englisch sprechend", True),
        ("Support Engineer (German/French/Dutch Speaking)", False),
        ("Support Engineer - French or Spanish Speaker", False),
        # With `and`, every language is needed.
        ("Support Engineer, Dutch and English Speaker", False),
        ("Support Engineer (English- and Portuguese-Speaking)", True),
        ("Support Engineer, Englisch und Deutsch sprechend", False),
        # Words before the list do not join it.
        ("Dutch Market Engineer, English Speaking", True),
    ],
)
def test_language_rule_reads_a_list_of_languages(title: str, passes: bool) -> None:
    result = check(posting(title=title), PROFILE)
    assert result == (() if passes else (Reason.LANGUAGE,))
