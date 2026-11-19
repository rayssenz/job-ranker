import json

import httpx
import pytest
from support import SEARCH, TOKEN, Handler, Recorder, answer, sample

from jobranker.config import Search
from jobranker.models import Posting, Remote
from jobranker.sources import linkedin
from jobranker.sources.base import SourceError


def fetch(recorder: Recorder, search: Search = SEARCH, limit: int = 50) -> linkedin.FetchResult:
    return linkedin.fetch(recorder.client, search, token=TOKEN, limit=limit)


def test_request_address_body_and_cost_cap() -> None:
    recorder = Recorder(answer(sample("linkedin"), status=201))
    fetch(recorder)
    (request,) = recorder.requests
    assert request.method == "POST"
    assert request.url.host == "api.apify.com"
    assert request.url.path == "/v2/actors/valig~linkedin-jobs-scraper/run-sync-get-dataset-items"
    assert dict(request.url.params) == {"maxTotalChargeUsd": "0.11"}
    assert json.loads(request.content) == {
        "keywords": "machine learning engineer",
        "location": "Lisbon",
        "datePosted": "r86400",
        "limit": 50,
    }


def test_cost_cap_follows_the_limit() -> None:
    assert linkedin.cost_cap(50) == 0.11
    assert linkedin.cost_cap(200) == 0.41
    assert linkedin.cost_cap(1) == 0.01


def test_token_is_in_header_not_in_address() -> None:
    recorder = Recorder(answer(sample("linkedin"), status=201))
    fetch(recorder)
    (request,) = recorder.requests
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in str(request.url)
    assert TOKEN not in request.content.decode()


def test_other_actor_can_be_named() -> None:
    recorder = Recorder(answer([], status=201))
    linkedin.fetch(recorder.client, SEARCH, token=TOKEN, limit=5, actor="someone~other-actor")
    assert recorder.requests[0].url.path.startswith("/v2/actors/someone~other-actor/")


def test_request_waits_longer_than_the_endpoint_limit() -> None:
    recorder = Recorder(answer([], status=201))
    fetch(recorder)
    timeout = recorder.requests[0].extensions["timeout"]
    assert timeout["read"] == linkedin.REQUEST_TIMEOUT_SECONDS > 300


def test_maps_fields() -> None:
    result = fetch(Recorder(answer(sample("linkedin"), status=201)))
    assert result.skipped == 0
    assert len(result.postings) == 3
    assert result.postings[0] == Posting(
        source="linkedin",
        board="",
        posting_id="9000000001",
        company="NORTHWIND ROBOTICS GmbH",
        title="ML Engineer",
        location="Lisbon, Portugal",
        remote=Remote.UNKNOWN,
        url="https://www.linkedin.example.test/jobs/view/ml-engineer-at-northwind-robotics-9000000001",
        description="Build and run perception models. Python and PyTorch.",
    )


def test_recruiter_fields_are_not_kept() -> None:
    result = fetch(Recorder(answer(sample("linkedin"), status=201)))
    for posting in result.postings:
        kept = repr(posting) + json.dumps(posting.model_dump(mode="json"))
        assert "Recruiter" not in kept
        assert "recruiter" not in kept


def test_never_returns_more_than_limit() -> None:
    result = fetch(Recorder(answer(sample("linkedin"), status=201)), limit=2)
    assert len(result.postings) == 2


@pytest.mark.parametrize(
    ("posted_within", "expected"),
    [("day", "r86400"), ("week", "r604800"), ("month", "r2592000")],
)
def test_posted_within_mapping(posted_within: str, expected: str) -> None:
    recorder = Recorder(answer([], status=201))
    search = Search.model_validate(
        {"keywords": "x", "location": "Lisbon", "posted_within": posted_within}
    )
    fetch(recorder, search)
    assert json.loads(recorder.requests[0].content)["datePosted"] == expected


def test_result_without_id_title_or_company_is_skipped_and_counted() -> None:
    body = [
        {"title": "Role", "companyName": "Quillmark"},
        {"id": "1", "companyName": "Quillmark"},
        {"id": "2", "title": "Role"},
        {"id": "3", "title": "Role", "companyName": "Quillmark"},
    ]
    result = fetch(Recorder(answer(body, status=201)))
    assert [p.posting_id for p in result.postings] == ["3"]
    assert result.skipped == 3


def test_empty_result_is_not_an_error() -> None:
    assert fetch(Recorder(answer([], status=201))).postings == []


@pytest.mark.parametrize("body", [{"error": {"type": "x"}}, "text", [1, 2]])
def test_wrong_shape_raises(body: object) -> None:
    with pytest.raises(SourceError) as error:
        fetch(Recorder(answer(body, status=201)))
    assert error.value.reason == "unexpected shape"


def _raise_connect(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError(f"failed with {TOKEN}", request=request)


def _raise_timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout(f"slow with {TOKEN}", request=request)


@pytest.mark.parametrize(
    ("handler", "reason"),
    [
        (answer({"error": {"message": f"bad token {TOKEN}"}}, status=401), "HTTP 401"),
        (answer({"error": {"type": "x402-payment-required"}}, status=402), "HTTP 402"),
        (answer({"error": {"type": "run-timeout-exceeded"}}, status=408), "HTTP 408"),
        (lambda request: httpx.Response(201, text=f"not json {TOKEN}"), "not JSON"),
        (_raise_connect, "connection error"),
        (_raise_timeout, "timeout"),
    ],
)
def test_failures_never_reveal_the_token(handler: Handler, reason: str) -> None:
    with pytest.raises(SourceError) as error:
        fetch(Recorder(handler))
    assert error.value.reason == reason
    assert TOKEN not in error.value.reason
    assert TOKEN not in str(error.value)
    assert TOKEN not in repr(error.value)
    assert error.value.__cause__ is None
