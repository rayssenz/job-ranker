"""Source adapters. Each one turns a source's response into posting records."""

from collections.abc import Callable

import httpx

from jobranker.config import Company
from jobranker.sources import ashby, greenhouse, lever, personio
from jobranker.sources.base import FetchResult

FeedFetch = Callable[[httpx.Client, Company], FetchResult]

FEEDS: dict[str, FeedFetch] = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
    "personio": personio.fetch,
}
