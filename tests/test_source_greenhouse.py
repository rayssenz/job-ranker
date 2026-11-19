import copy

import pytest
from support import GREENHOUSE, Recorder, answer, sample

from jobranker.models import Posting, Remote
from jobranker.sources import FEEDS, greenhouse
from jobranker.sources.base import SourceError


def test_request_address() -> None:
    recorder = Recorder(answer(sample("greenhouse")))
    greenhouse.fetch(recorder.client, GREENHOUSE)
    (request,) = recorder.requests
    assert request.method == "GET"
    assert request.url.host == "boards-api.greenhouse.io"
    assert request.url.path == "/v1/boards/northwindrobotics/jobs"
    assert dict(request.url.params) == {"content": "true"}


def test_maps_fields() -> None:
    result = greenhouse.fetch(Recorder(answer(sample("greenhouse"))).client, GREENHOUSE)
    assert result.skipped == 0
    assert len(result.postings) == 3
    assert result.postings[0] == Posting(
        source="greenhouse",
        board="northwindrobotics",
        posting_id="1001",
        company="Northwind Robotics",
        title="ML Engineer",
        location="Lisbon, Portugal",
        remote=Remote.UNKNOWN,
        url="https://boards.example.test/northwindrobotics/jobs/1001",
        description="Build & run perception models.\nPython\nPyTorch",
    )


def test_description_is_plain_text() -> None:
    result = greenhouse.fetch(Recorder(answer(sample("greenhouse"))).client, GREENHOUSE)
    for posting in result.postings:
        assert posting.description
        for mark in ("<", ">", "&lt;", "&amp;", "&quot;"):
            assert mark not in posting.description


def test_empty_board_is_not_an_error() -> None:
    result = greenhouse.fetch(
        Recorder(answer({"jobs": [], "meta": {"total": 0}})).client, GREENHOUSE
    )
    assert result.postings == []
    assert result.skipped == 0


def test_posting_without_title_or_id_is_skipped_and_counted() -> None:
    body = copy.deepcopy(sample("greenhouse"))
    del body["jobs"][0]["title"]
    del body["jobs"][1]["id"]
    result = greenhouse.fetch(Recorder(answer(body)).client, GREENHOUSE)
    assert [p.posting_id for p in result.postings] == ["1003"]
    assert result.skipped == 2


def test_missing_optional_fields_become_empty() -> None:
    body = {"jobs": [{"id": 7, "title": "Engineer", "location": None}]}
    (posting,) = greenhouse.fetch(Recorder(answer(body)).client, GREENHOUSE).postings
    assert (posting.location, posting.url, posting.description) == ("", "", "")


@pytest.mark.parametrize("body", [[], {"jobs": "none"}, {"other": 1}, "text", {"jobs": [5]}])
def test_wrong_shape_raises(body: object) -> None:
    with pytest.raises(SourceError) as error:
        greenhouse.fetch(Recorder(answer(body)).client, GREENHOUSE)
    assert error.value.reason == "unexpected shape"


def test_feeds_table_lists_three_adapters() -> None:
    assert sorted(FEEDS) == ["ashby", "greenhouse", "lever"]
