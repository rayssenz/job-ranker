"""Ashby job board feed. Documentation: developers.ashbyhq.com/docs/public-job-posting-api"""

from typing import Any

import httpx

from jobranker.config import Company
from jobranker.models import Posting, Remote
from jobranker.sources.base import FetchResult, SourceError, get_json, items, text

SOURCE = "ashby"
URL = "https://api.ashbyhq.com/posting-api/job-board/{token}"
# isRemote is also true for hybrid postings, so only workplaceType is read.
_REMOTE = {"Remote": Remote.YES, "Hybrid": Remote.NO, "OnSite": Remote.NO}


def _locations(job: dict[str, Any]) -> str:
    """The primary location followed by the secondary ones, each named once."""
    secondary = job.get("secondaryLocations")
    places = [job.get("location")]
    if isinstance(secondary, list):
        places += [entry.get("location") for entry in secondary if isinstance(entry, dict)]
    # A job offered in several places must not be judged by its first place alone.
    return "; ".join(dict.fromkeys(name for name in map(text, places) if name))


def fetch(client: httpx.Client, company: Company) -> FetchResult:
    body = get_json(client, "GET", URL.format(token=company.token))
    if not isinstance(body, dict):
        raise SourceError("unexpected shape")
    postings: list[Posting] = []
    skipped = 0
    for job in items(body.get("jobs")):
        if job.get("isListed") is False:
            continue
        url = text(job.get("jobUrl"))
        # `id` is in the live response and in no documented field table.
        posting_id, title = text(job.get("id")) or url, text(job.get("title"))
        if not posting_id or not title:
            skipped += 1
            continue
        postings.append(
            Posting(
                source=SOURCE,
                board=company.token,
                posting_id=posting_id,
                company=company.name,
                title=title,
                location=_locations(job),
                remote=_REMOTE.get(text(job.get("workplaceType")), Remote.UNKNOWN),
                url=url,
                description=text(job.get("descriptionPlain")),
            )
        )
    return FetchResult(postings, skipped)
