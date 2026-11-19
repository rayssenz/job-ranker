import httpx
import pytest
from support import LEVER, Recorder, answer, sample

from jobranker.config import Company
from jobranker.models import Posting, Remote
from jobranker.sources import lever
from jobranker.sources.base import SourceError


def made_up(number: int) -> dict[str, object]:
    return {"id": f"id-{number}", "text": f"Role {number}", "workplaceType": "remote"}


def test_global_and_eu_hosts() -> None:
    eu = Recorder(answer([]))
    lever.fetch(eu.client, LEVER)
    assert eu.requests[0].url.host == "api.eu.lever.co"

    world = Recorder(answer([]))
    lever.fetch(world.client, Company(name="Bluefjord Labs", feed="lever", token="bluefjord"))
    (request,) = world.requests
    assert request.url.host == "api.lever.co"
    assert request.url.path == "/v0/postings/bluefjord"
    assert dict(request.url.params) == {"mode": "json", "skip": "0", "limit": "100"}


def test_pages_until_short_page() -> None:
    items = [made_up(n) for n in range(240)]

    def handler(request: httpx.Request) -> httpx.Response:
        skip = int(request.url.params["skip"])
        return httpx.Response(200, json=items[skip : skip + 100])

    recorder = Recorder(handler)
    result = lever.fetch(recorder.client, LEVER)
    assert [r.url.params["skip"] for r in recorder.requests] == ["0", "100", "200"]
    assert len(result.postings) == 240
    assert len({p.posting_id for p in result.postings}) == 240


def test_full_last_page_needs_one_empty_request() -> None:
    items = [made_up(n) for n in range(100)]

    def handler(request: httpx.Request) -> httpx.Response:
        skip = int(request.url.params["skip"])
        return httpx.Response(200, json=items[skip : skip + 100])

    recorder = Recorder(handler)
    assert len(lever.fetch(recorder.client, LEVER).postings) == 100
    assert len(recorder.requests) == 2


def test_maps_fields_and_joins_lists_and_closing_text() -> None:
    result = lever.fetch(Recorder(answer(sample("lever"))).client, LEVER)
    assert len(result.postings) == 3
    assert result.postings[0] == Posting(
        source="lever",
        board="bluefjord",
        posting_id="0a000000-0000-4000-8000-000000000001",
        company="Bluefjord Labs",
        title="Data Engineer",
        location="Oslo",
        remote=Remote.NO,
        url="https://jobs.example.test/bluefjord/0a000000-0000-4000-8000-000000000001",
        description=(
            "We move data.\nYou will own the pipelines.\n\n"
            "Requirements\nSQL\nAirflow & dbt\n\n"
            "Benefits\nTrain pass\n\n"
            "Apply with a short note."
        ),
    )
    assert result.postings[1].description == "Model the warehouse."
    assert result.postings[2].description == "Keep the office running."


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("remote", Remote.YES),
        ("hybrid", Remote.NO),
        ("on-site", Remote.NO),
        ("unspecified", Remote.UNKNOWN),
        (None, Remote.UNKNOWN),
    ],
)
def test_workplace_type_mapping(value: str | None, expected: Remote) -> None:
    item: dict[str, object] = {"id": "x", "text": "Role"}
    if value is not None:
        item["workplaceType"] = value
    (posting,) = lever.fetch(Recorder(answer([item])).client, LEVER).postings
    assert posting.remote is expected


def test_posting_without_title_is_skipped_and_counted() -> None:
    result = lever.fetch(Recorder(answer([{"id": "x"}, made_up(1)])).client, LEVER)
    assert len(result.postings) == 1
    assert result.skipped == 1


@pytest.mark.parametrize("body", [{"jobs": []}, "text", [3]])
def test_wrong_shape_raises(body: object) -> None:
    with pytest.raises(SourceError) as error:
        lever.fetch(Recorder(answer(body)).client, LEVER)
    assert error.value.reason == "unexpected shape"
