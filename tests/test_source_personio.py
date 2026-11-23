import httpx
import pytest
from support import PERSONIO, Recorder, sample_text

from jobranker.models import Posting, Remote
from jobranker.sources import personio
from jobranker.sources.base import FetchResult, SourceError

EMPTY = '<?xml version="1.0" encoding="UTF-8"?>\n<workzag-jobs></workzag-jobs>\n'


def xml(body: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, text=body, headers={"Content-Type": "text/xml"})


def feeds(de: httpx.Response | None = None, en: httpx.Response | None = None) -> Recorder:
    """Answer each language with its sample unless a response is given for it."""
    answers = {
        "de": de or xml(sample_text("personio_de.xml")),
        "en": en or xml(sample_text("personio_en.xml")),
    }
    return Recorder(lambda request: answers[request.url.params["language"]])


def by_id(result: FetchResult) -> dict[str, Posting]:
    return {p.posting_id: p for p in result.postings}


def test_requests_both_languages() -> None:
    recorder = feeds()
    personio.fetch(recorder.client, PERSONIO)
    assert [(r.method, r.url.host, r.url.path, dict(r.url.params)) for r in recorder.requests] == [
        ("GET", "larkspur.jobs.personio.de", "/xml", {"language": "de"}),
        ("GET", "larkspur.jobs.personio.de", "/xml", {"language": "en"}),
    ]


def test_maps_fields() -> None:
    result = personio.fetch(feeds().client, PERSONIO)
    assert result.postings[0] == Posting(
        source="personio",
        board="larkspur",
        posting_id="101",
        company="Larkspur Analytics",
        title="Backend Engineer",
        location="Lisbon; Porto",
        remote=Remote.UNKNOWN,
        url="https://larkspur.jobs.personio.de/job/101",
        description="Aufgaben\nDatenpipelines bauen.\nProfil\nPython\nSQL",
    )


def test_keeps_longer_description_per_role() -> None:
    postings = by_id(personio.fetch(feeds().client, PERSONIO))
    assert postings["101"].description.startswith("Aufgaben")
    assert postings["102"].description == (
        "About the role\nBuild the forecasting service.\nWork with the data team."
    )


def test_remote_office_marks_remote_and_title_is_unescaped() -> None:
    posting = by_id(personio.fetch(feeds().client, PERSONIO))["102"]
    assert posting.remote == Remote.YES
    assert posting.title == "R&D Engineer"


def test_role_without_title_is_skipped() -> None:
    result = personio.fetch(feeds().client, PERSONIO)
    assert [p.posting_id for p in result.postings] == ["101", "102"]
    assert result.skipped == 1


def test_role_only_in_one_language_is_kept() -> None:
    extra = sample_text("personio_en.xml").replace(
        "</workzag-jobs>",
        "<position><id>104</id><office>Porto</office><name>Data Intern</name></position>"
        "</workzag-jobs>",
    )
    postings = by_id(personio.fetch(feeds(en=xml(extra)).client, PERSONIO))
    assert postings["104"].title == "Data Intern"
    assert list(postings) == ["101", "102", "104"]


def test_one_language_failing_uses_the_other() -> None:
    result = personio.fetch(feeds(en=xml("", status=500)).client, PERSONIO)
    assert [p.posting_id for p in result.postings] == ["101", "102"]
    assert by_id(result)["102"].description == "Über die Rolle"


def test_both_languages_failing_raises_first_reason() -> None:
    recorder = feeds(de=xml("missing", status=404), en=xml("missing", status=404))
    with pytest.raises(SourceError) as error:
        personio.fetch(recorder.client, PERSONIO)
    assert error.value.reason == "HTTP 404"


@pytest.mark.parametrize("declaration", ["<!DOCTYPE x>", '<!ENTITY y "z">', "<!doctype x>"])
def test_doctype_or_entity_is_refused(declaration: str) -> None:
    body = sample_text("personio_de.xml").replace("<workzag-jobs>", declaration + "<workzag-jobs>")
    with pytest.raises(SourceError) as error:
        personio.fetch(feeds(de=xml(body), en=xml(body)).client, PERSONIO)
    assert error.value.reason == "unexpected shape"


def test_html_answer_is_not_xml() -> None:
    page = xml("<html><body>oops")
    with pytest.raises(SourceError) as error:
        personio.fetch(feeds(de=page, en=page).client, PERSONIO)
    assert error.value.reason == "not XML"


def test_other_root_element_is_unexpected_shape() -> None:
    page = xml("<html><body>oops</body></html>")
    with pytest.raises(SourceError) as error:
        personio.fetch(feeds(de=page, en=page).client, PERSONIO)
    assert error.value.reason == "unexpected shape"


def test_empty_feed_gives_no_postings() -> None:
    result = personio.fetch(feeds(de=xml(EMPTY), en=xml(EMPTY)).client, PERSONIO)
    assert result == FetchResult([], 0)
