import pytest
from support import ASHBY, Recorder, answer, sample

from jobranker.models import Posting, Remote
from jobranker.sources import ashby
from jobranker.sources.base import SourceError


def test_request_address() -> None:
    recorder = Recorder(answer(sample("ashby")))
    ashby.fetch(recorder.client, ASHBY)
    (request,) = recorder.requests
    assert request.method == "GET"
    assert request.url.host == "api.ashbyhq.com"
    assert request.url.path == "/posting-api/job-board/tessellate"
    assert dict(request.url.params) == {}


def test_maps_fields() -> None:
    result = ashby.fetch(Recorder(answer(sample("ashby"))).client, ASHBY)
    assert result.postings[0] == Posting(
        source="ashby",
        board="tessellate",
        posting_id="0b000000-0000-4000-8000-000000000001",
        company="Tessellate Systems",
        title="Backend Engineer",
        location="Vienna",
        remote=Remote.NO,
        url="https://jobs.example.test/tessellate/0b000000-0000-4000-8000-000000000001",
        description="Build the tiling service.",
    )


def test_unlisted_posting_is_left_out_and_not_counted_as_skipped() -> None:
    result = ashby.fetch(Recorder(answer(sample("ashby"))).client, ASHBY)
    assert [p.title for p in result.postings] == [
        "Backend Engineer",
        "Developer Advocate",
        "Support Engineer",
    ]
    assert result.skipped == 0


def test_missing_id_falls_back_to_job_url() -> None:
    body = {"jobs": [{"title": "Role", "jobUrl": "https://jobs.example.test/t/role"}]}
    (posting,) = ashby.fetch(Recorder(answer(body)).client, ASHBY).postings
    assert posting.posting_id == "https://jobs.example.test/t/role"


def test_posting_without_id_and_url_is_skipped() -> None:
    result = ashby.fetch(Recorder(answer({"jobs": [{"title": "Role"}]})).client, ASHBY)
    assert result.postings == []
    assert result.skipped == 1


@pytest.mark.parametrize(
    ("workplace", "is_remote", "expected"),
    [
        ("Remote", True, Remote.YES),
        ("Hybrid", True, Remote.NO),
        ("OnSite", False, Remote.NO),
        (None, True, Remote.UNKNOWN),
    ],
)
def test_workplace_type_mapping(workplace: str | None, is_remote: bool, expected: Remote) -> None:
    job: dict[str, object] = {"id": "x", "title": "Role", "isRemote": is_remote}
    if workplace is not None:
        job["workplaceType"] = workplace
    (posting,) = ashby.fetch(Recorder(answer({"jobs": [job]})).client, ASHBY).postings
    assert posting.remote is expected


@pytest.mark.parametrize("body", [[], {"jobs": {}}, {"apiVersion": "1"}, {"jobs": ["x"]}])
def test_wrong_shape_raises(body: object) -> None:
    with pytest.raises(SourceError) as error:
        ashby.fetch(Recorder(answer(body)).client, ASHBY)
    assert error.value.reason == "unexpected shape"


@pytest.mark.parametrize(
    ("secondary", "expected"),
    [
        ([{"location": "Lisbon"}, {"location": "Porto"}], "Vienna; Lisbon; Porto"),
        ([{"location": "Vienna"}, {"location": " Lisbon "}], "Vienna; Lisbon"),
        ([{"location": ""}, {}, None, "Graz", {"location": 7}], "Vienna; 7"),
        ("not a list", "Vienna"),
        (None, "Vienna"),
    ],
)
def test_secondary_locations_follow_the_primary_one(secondary: object, expected: str) -> None:
    body = sample("ashby")
    body["jobs"][0]["secondaryLocations"] = secondary
    result = ashby.fetch(Recorder(answer(body)).client, ASHBY)
    assert result.postings[0].location == expected


def test_secondary_location_is_used_when_the_primary_is_missing() -> None:
    body = sample("ashby")
    body["jobs"][0]["location"] = None
    body["jobs"][0]["secondaryLocations"] = [{"location": "Lisbon"}]
    result = ashby.fetch(Recorder(answer(body)).client, ASHBY)
    assert result.postings[0].location == "Lisbon"
