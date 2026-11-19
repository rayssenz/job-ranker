import pytest
from pydantic import ValidationError

from jobranker.models import Posting, Remote


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


def test_posting_is_frozen() -> None:
    posting = make_posting()
    with pytest.raises(ValidationError):
        posting.title = "Other"
