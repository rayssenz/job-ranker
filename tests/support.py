"""Shared test helpers: sample files and a mock HTTP client that records requests."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from jobranker.config import Company, Search

SAMPLES = Path(__file__).parent / "samples"

Handler = Callable[[httpx.Request], httpx.Response]
Route = Handler

GREENHOUSE = Company(name="Northwind Robotics", feed="greenhouse", token="northwindrobotics")
LEVER = Company(name="Bluefjord Labs", feed="lever", token="bluefjord", region="eu")
ASHBY = Company(name="Tessellate Systems", feed="ashby", token="tessellate")
PERSONIO = Company(name="Larkspur Analytics", feed="personio", token="larkspur")
SEARCH = Search(keywords="machine learning engineer", location="Lisbon")
TOKEN = "test-token-123"


def sample(name: str) -> Any:
    return json.loads((SAMPLES / f"{name}.json").read_text())


def sample_text(name: str) -> str:
    return (SAMPLES / name).read_text()


class Recorder:
    """Wraps a handler, keeps the requests it saw and offers a client that uses it."""

    def __init__(self, handler: Handler) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler
        self.client = httpx.Client(transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)


def answer(body: Any, status: int = 200) -> Handler:
    return lambda request: httpx.Response(status, json=body)


def routes(**overrides: Route) -> Recorder:
    """A client that serves the sample for each host. An override replaces one host's answer."""
    table: dict[str, Route] = {
        "boards-api.greenhouse.io": lambda r: httpx.Response(200, json=sample("greenhouse")),
        "api.eu.lever.co": lambda r: httpx.Response(200, json=sample("lever")),
        "api.ashbyhq.com": lambda r: httpx.Response(200, json=sample("ashby")),
        "api.apify.com": lambda r: httpx.Response(201, json=sample("linkedin")),
        "larkspur.jobs.personio.de": lambda r: httpx.Response(
            200,
            text=sample_text(f"personio_{r.url.params['language']}.xml"),
            headers={"Content-Type": "text/xml"},
        ),
    }
    names = {
        "greenhouse": "boards-api.greenhouse.io",
        "lever": "api.eu.lever.co",
        "ashby": "api.ashbyhq.com",
        "apify": "api.apify.com",
        "personio": "larkspur.jobs.personio.de",
    }
    for name, route in overrides.items():
        table[names[name]] = route
    return Recorder(lambda request: table[request.url.host](request))
