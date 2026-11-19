"""Greenhouse job board feed. Documentation: developers.greenhouse.io/job-board.html"""

import html

import httpx

from jobranker.config import Company
from jobranker.models import Posting
from jobranker.sources.base import FetchResult, SourceError, get_json, items, text
from jobranker.text import html_to_text

SOURCE = "greenhouse"
URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


def fetch(client: httpx.Client, company: Company) -> FetchResult:
    # The description is only returned with content=true.
    body = get_json(client, "GET", URL.format(token=company.token), params={"content": "true"})
    if not isinstance(body, dict):
        raise SourceError("unexpected shape")
    postings: list[Posting] = []
    skipped = 0
    for job in items(body.get("jobs")):
        posting_id, title = text(job.get("id")), text(job.get("title"))
        if not posting_id or not title:
            skipped += 1
            continue
        location = job.get("location")
        postings.append(
            Posting(
                source=SOURCE,
                board=company.token,
                posting_id=posting_id,
                company=company.name,
                title=title,
                location=text(location.get("name")) if isinstance(location, dict) else "",
                url=text(job.get("absolute_url")),
                # The content arrives as HTML with its characters escaped once.
                description=html_to_text(html.unescape(text(job.get("content")))),
            )
        )
    return FetchResult(postings, skipped)
