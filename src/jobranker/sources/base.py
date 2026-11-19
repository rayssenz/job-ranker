"""What every source adapter shares: the result type, the error type and the request helper."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import httpx

from jobranker.models import Posting


class SourceError(Exception):
    """A source that could not be read. `reason` is short and safe to print and store."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class FetchResult:
    postings: list[Posting] = field(default_factory=list)
    skipped: int = 0


def get_json(client: httpx.Client, method: str, url: str, **kwargs: Any) -> Any:
    """Send one request and return the parsed JSON body.

    The reasons raised here never include the response body, the headers or the text of
    the underlying exception, because any of them can carry a token.
    """
    try:
        response = client.request(method, url, **kwargs)
    except httpx.TimeoutException:
        raise SourceError("timeout") from None
    except httpx.HTTPError:
        raise SourceError("connection error") from None
    # Redirects are not followed, so a moved board is reported with its own status.
    if not response.is_success:
        raise SourceError(f"HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError:
        raise SourceError("not JSON") from None


def items(body: Any) -> list[dict[str, Any]]:
    """Return `body` as a list of objects, or raise when it is anything else."""
    if not isinstance(body, list) or not all(isinstance(item, dict) for item in body):
        raise SourceError("unexpected shape")
    return body


def text(value: Any) -> str:
    """A field as stripped text. Missing, null and non-text values give an empty string."""
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, str | int):
        return str(value).strip()
    return ""


def places(names: Iterable[Any]) -> str:
    """Place names as one text, each named once, in the order given.

    A job offered in several places keeps all of them, so it is not judged by the first one.
    """
    return "; ".join(dict.fromkeys(name for name in map(text, names) if name))


def values(entries: Any, key: str) -> list[Any]:
    """The value of `key` in each object of a list. Anything else gives an empty list."""
    if not isinstance(entries, list):
        return []
    return [entry.get(key) for entry in entries if isinstance(entry, dict)]
