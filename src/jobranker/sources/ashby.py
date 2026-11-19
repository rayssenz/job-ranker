"""Ashby job board feed. Documentation: developers.ashbyhq.com/docs/public-job-posting-api"""

import httpx

from jobranker.config import Company
from jobranker.models import Posting, Remote
from jobranker.sources.base import FetchResult, SourceError, get_json, items, places, text, values

SOURCE = "ashby"
URL = "https://api.ashbyhq.com/posting-api/job-board/{token}"
# isRemote is also true for hybrid postings, so only workplaceType is read.
_REMOTE = {"Remote": Remote.YES, "Hybrid": Remote.NO, "OnSite": Remote.NO}


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
                location=places(
                    [job.get("location"), *values(job.get("secondaryLocations"), "location")]
                ),
                remote=_REMOTE.get(text(job.get("workplaceType")), Remote.UNKNOWN),
                url=url,
                description=text(job.get("descriptionPlain")),
            )
        )
    return FetchResult(postings, skipped)
