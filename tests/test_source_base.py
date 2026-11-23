import httpx
import pytest
from support import Recorder

from jobranker.sources.base import SourceError, get_json, get_text

URL = "https://feeds.example.test/jobs"


def fetch(recorder: Recorder) -> object:
    return get_json(recorder.client, "GET", URL)


def test_returns_parsed_json() -> None:
    recorder = Recorder(lambda request: httpx.Response(200, json={"jobs": []}))
    assert fetch(recorder) == {"jobs": []}


def test_error_status_reason() -> None:
    recorder = Recorder(lambda request: httpx.Response(404, text="secret detail"))
    with pytest.raises(SourceError) as error:
        fetch(recorder)
    assert error.value.reason == "HTTP 404"
    assert "secret detail" not in str(error.value)


def test_timeout_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(SourceError) as error:
        fetch(Recorder(handler))
    assert error.value.reason == "timeout"


def test_connection_error_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret detail", request=request)

    with pytest.raises(SourceError) as error:
        fetch(Recorder(handler))
    assert error.value.reason == "connection error"
    assert "secret detail" not in str(error.value)


def test_not_json_reason() -> None:
    recorder = Recorder(lambda request: httpx.Response(200, text="<html>down</html>"))
    with pytest.raises(SourceError) as error:
        fetch(recorder)
    assert error.value.reason == "not JSON"


def test_redirect_is_reported_with_its_status() -> None:
    recorder = Recorder(
        lambda request: httpx.Response(301, headers={"Location": "https://example.test/new"})
    )
    with pytest.raises(SourceError) as error:
        get_json(recorder.client, "GET", "https://example.test/feed")
    assert error.value.reason == "HTTP 301"


def test_get_text_returns_body() -> None:
    recorder = Recorder(lambda request: httpx.Response(200, text="<a/>"))
    assert get_text(recorder.client, URL) == "<a/>"


def test_get_text_error_status_reason() -> None:
    recorder = Recorder(lambda request: httpx.Response(404, text="secret detail"))
    with pytest.raises(SourceError) as error:
        get_text(recorder.client, URL)
    assert error.value.reason == "HTTP 404"
    assert "secret detail" not in str(error.value)


def test_get_text_timeout_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(SourceError) as error:
        get_text(Recorder(handler).client, URL)
    assert error.value.reason == "timeout"
