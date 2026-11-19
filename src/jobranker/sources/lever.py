"""Lever postings feed. Documentation: github.com/lever/postings-api"""

from typing import Any

import httpx

from jobranker.config import Company
from jobranker.models import Posting, Remote
from jobranker.sources.base import FetchResult, SourceError, get_json, items, places, text
from jobranker.text import html_to_text

SOURCE = "lever"
HOSTS = {"global": "api.lever.co", "eu": "api.eu.lever.co"}
PAGE_SIZE = 100
# The documentation gives no maximum page size, so the adapter pages until a short page.
# The cap stops a feed that ignores `skip` from being read forever.
MAX_PAGES = 50
_REMOTE = {"remote": Remote.YES, "hybrid": Remote.NO, "on-site": Remote.NO}


def _description(item: dict[str, Any]) -> str:
    # descriptionPlain leaves out the requirement lists and the closing text.
    parts = [text(item.get("descriptionPlain"))]
    lists = item.get("lists")
    for entry in lists if isinstance(lists, list) else []:
        if isinstance(entry, dict):
            heading, content = text(entry.get("text")), html_to_text(text(entry.get("content")))
            parts.append("\n".join(part for part in (heading, content) if part))
    parts.append(text(item.get("additionalPlain")))
    return "\n\n".join(part for part in parts if part)


def fetch(client: httpx.Client, company: Company) -> FetchResult:
    url = f"https://{HOSTS[company.region]}/v0/postings/{company.token}"
    postings: list[Posting] = []
    skipped = 0
    for page in range(MAX_PAGES):
        params = {"mode": "json", "skip": page * PAGE_SIZE, "limit": PAGE_SIZE}
        batch = items(get_json(client, "GET", url, params=params))
        for item in batch:
            posting_id, title = text(item.get("id")), text(item.get("text"))
            if not posting_id or not title:
                skipped += 1
                continue
            categories = item.get("categories")
            if not isinstance(categories, dict):
                categories = {}
            every = categories.get("allLocations")
            postings.append(
                Posting(
                    source=SOURCE,
                    board=company.token,
                    posting_id=posting_id,
                    company=company.name,
                    title=title,
                    location=places(
                        [categories.get("location"), *(every if isinstance(every, list) else [])]
                    ),
                    remote=_REMOTE.get(text(item.get("workplaceType")), Remote.UNKNOWN),
                    url=text(item.get("hostedUrl")),
                    description=_description(item),
                )
            )
        if len(batch) < PAGE_SIZE:
            return FetchResult(postings, skipped)
    raise SourceError("too many pages")
