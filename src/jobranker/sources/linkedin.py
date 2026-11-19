"""LinkedIn job search through an Apify actor that reads the public job pages.

Documentation: docs.apify.com/api/v2/act-run-sync-get-dataset-items-post
The actor is published by a third party. Its name is a setting, and `_to_posting` is the
only place that knows its output fields.
"""

from typing import Any

import httpx

from jobranker.config import Search
from jobranker.models import Posting
from jobranker.sources.base import FetchResult, get_json, items, text

SOURCE = "linkedin"
DEFAULT_ACTOR = "valig~linkedin-jobs-scraper"
URL = "https://api.apify.com/v2/actors/{actor}/run-sync-get-dataset-items"
# The endpoint answers 408 after 300 seconds, so the client waits a little longer.
REQUEST_TIMEOUT_SECONDS = 320.0
# Upper bound used for the cost cap, above the default actor's price per result.
MAX_USD_PER_RESULT = 0.002
_RUN_START_ALLOWANCE_USD = 0.01
_DATE_POSTED = {"day": "r86400", "week": "r604800", "month": "r2592000"}

__all__ = ["DEFAULT_ACTOR", "FetchResult", "cost_cap", "fetch"]


def cost_cap(limit: int) -> float:
    """The most one request may cost. Apify stops charging at this amount."""
    return round(limit * MAX_USD_PER_RESULT + _RUN_START_ALLOWANCE_USD, 2)


def _to_posting(item: dict[str, Any]) -> Posting | None:
    # Only these fields are read. The recruiter's name and profile address are dropped.
    posting_id, title, company = (
        text(item.get("id")),
        text(item.get("title")),
        text(item.get("companyName")),
    )
    if not posting_id or not title or not company:
        return None
    return Posting(
        source=SOURCE,
        board="",
        posting_id=posting_id,
        company=company,
        title=title,
        location=text(item.get("location")),
        url=text(item.get("url")),
        description=text(item.get("description")),
    )


def fetch(
    client: httpx.Client,
    search: Search,
    *,
    token: str,
    limit: int,
    actor: str = DEFAULT_ACTOR,
) -> FetchResult:
    """Run one search and return at most `limit` postings."""
    body = get_json(
        client,
        "POST",
        URL.format(actor=actor),
        params={"maxTotalChargeUsd": cost_cap(limit)},
        # The token goes in the header so it is never part of an address.
        headers={"Authorization": f"Bearer {token}"},
        json={
            "keywords": search.keywords,
            "location": search.location,
            "datePosted": _DATE_POSTED[search.posted_within],
            "limit": limit,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    postings: list[Posting] = []
    skipped = 0
    for item in items(body)[:limit]:
        posting = _to_posting(item)
        if posting is None:
            skipped += 1
        else:
            postings.append(posting)
    return FetchResult(postings, skipped)
