import pytest
from pydantic import ValidationError

from jobranker.models import Posting, Remote, Verdict


def make_posting(**changes: str) -> Posting:
    fields = {
        "source": "greenhouse",
        "board": "northwindrobotics",
        "posting_id": "1001",
        "company": "Northwind Robotics",
        "title": "ML Engineer",
        "location": "Lisbon",
        "url": "https://example.test/jobs/1001",
        "description": "Build models.",
    }
    return Posting.model_validate(fields | changes)


def test_remote_defaults_to_unknown() -> None:
    assert make_posting().remote is Remote.UNKNOWN


def test_hash_changes_with_description_and_not_with_url() -> None:
    base = make_posting()
    assert make_posting(description="Build other models.").content_hash != base.content_hash
    assert make_posting(url="https://example.test/other").content_hash == base.content_hash
    assert len(base.content_hash) == 64


def test_hash_changes_with_title_location_and_remote() -> None:
    base = make_posting()
    assert make_posting(title="Data Engineer").content_hash != base.content_hash
    assert make_posting(location="Porto").content_hash != base.content_hash
    assert make_posting(remote="yes").content_hash != base.content_hash


def test_hash_keeps_field_borders() -> None:
    a = make_posting(title="ML", location="Engineer Lisbon")
    b = make_posting(title="ML Engineer", location="Lisbon")
    assert a.content_hash != b.content_hash


def test_match_key_ignores_case_punctuation_and_legal_form() -> None:
    a = make_posting(company="Northwind Robotics GmbH", title="ML Engineer (m/f/d)")
    b = make_posting(company="northwind robotics", title="ML engineer m/f/d")
    assert a.match_key == b.match_key


def test_match_key_differs_for_other_title() -> None:
    assert make_posting().match_key != make_posting(title="Data Engineer").match_key


def test_match_key_tells_c_plus_plus_c_sharp_and_c_apart() -> None:
    titles = ("C++ Developer", "C# Developer", "C Developer")
    assert len({make_posting(title=title).match_key for title in titles}) == 3


def test_match_key_tells_dot_net_from_net() -> None:
    assert (
        make_posting(title=".NET Developer").match_key
        != make_posting(title="NET Developer").match_key
    )


@pytest.mark.parametrize("changes", [{"title": "???"}, {"company": "---"}])
def test_match_key_is_empty_without_a_company_or_title_word(changes: dict[str, str]) -> None:
    assert make_posting(**changes).match_key == ""


def test_posting_is_frozen() -> None:
    posting = make_posting()
    with pytest.raises(ValidationError):
        posting.title = "Other"


def test_verdict_takes_only_yes_or_no_and_no_unknown_field() -> None:
    fields = {
        "decision": "yes",
        "reasons": ["Fits."],
        "matched": [],
        "missing": [],
        "cut": False,
        "model": "model-a",
        "input_tokens": 1,
        "output_tokens": 1,
        "duration_ms": 1,
        "cost_usd": 0.0,
    }
    verdict = Verdict.model_validate(fields)
    assert verdict.reasons == ("Fits.",)
    with pytest.raises(ValidationError):
        Verdict.model_validate(fields | {"decision": "maybe"})
    with pytest.raises(ValidationError):
        Verdict.model_validate(fields | {"score": 4})
    with pytest.raises(ValidationError):
        verdict.decision = "no"
