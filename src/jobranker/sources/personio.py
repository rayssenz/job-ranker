"""Personio job feed. The public XML feed is `https://{token}.jobs.personio.de/xml`.

Personio holds each role's description in the language the company wrote it in. Asked in
the other language, the feed returns the same role with an almost empty description. The
feed is therefore read in German and in English, and each role keeps the longer description.
"""

import re
import xml.etree.ElementTree as ET

import httpx

from jobranker.config import Company
from jobranker.models import Posting, Remote
from jobranker.sources.base import FetchResult, SourceError, get_text, places, text
from jobranker.text import html_to_text

SOURCE = "personio"
URL = "https://{token}.jobs.personio.de/xml"
JOB_URL = "https://{token}.jobs.personio.de/job/{id}"
LANGUAGES = ("de", "en")
ROOT = "workzag-jobs"
NOT_FOUND = "HTTP 404"
# A declared document type or entity could make the reader load outside files or expand
# text without limit. Personio's feed has neither, so an answer with one is refused.
_DECLARATION = re.compile(r"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)


def fetch(client: httpx.Client, company: Company) -> FetchResult:
    answers: list[tuple[dict[str, Posting | None], int]] = []
    errors: list[SourceError] = []
    for language in LANGUAGES:
        try:
            body = get_text(client, URL.format(token=company.token), params={"language": language})
            answers.append(_read(body, company))
        except SourceError as error:
            # Only a language the company does not publish (404) is left out. Any other
            # failure fails the company for this run, so a passing outage cannot replace
            # stored descriptions with the near-empty text of the other language.
            if error.reason != NOT_FOUND:
                raise
            errors.append(error)
    if not answers:
        raise errors[0]
    return _merge(answers)


def _read(body: str, company: Company) -> tuple[dict[str, Posting | None], int]:
    """The roles of one answer by ID (None for a role without a title) and the roles without ID."""
    if _DECLARATION.search(body):
        raise SourceError("unexpected shape")
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise SourceError("not XML") from None
    if root.tag != ROOT:
        raise SourceError("unexpected shape")
    roles: dict[str, Posting | None] = {}
    without_id = 0
    for position in root.iter("position"):
        posting_id = text(position.findtext("id"))
        if not posting_id:
            without_id += 1
            continue
        roles[posting_id] = _posting(position, posting_id, company)
    return roles, without_id


def _posting(position: ET.Element, posting_id: str, company: Company) -> Posting | None:
    title = text(position.findtext("name"))
    if not title:
        return None
    offices = [
        position.findtext("office"),
        *(o.text for o in position.iterfind("additionalOffices/office")),
    ]
    location = places(offices)
    return Posting(
        source=SOURCE,
        board=company.token,
        posting_id=posting_id,
        company=company.name,
        title=title,
        location=location,
        remote=Remote.YES if "remote" in location.lower() else Remote.UNKNOWN,
        url=JOB_URL.format(token=company.token, id=posting_id),
        description=_description(position),
    )


def _description(position: ET.Element) -> str:
    parts: list[str] = []
    for entry in position.iterfind("jobDescriptions/jobDescription"):
        parts.append(text(entry.findtext("name")))
        parts.append(html_to_text(entry.findtext("value") or ""))
    return "\n".join(part for part in parts if part)


def _merge(answers: list[tuple[dict[str, Posting | None], int]]) -> FetchResult:
    """One posting per role ID, in order of first appearance, with the longer description."""
    ids = list(dict.fromkeys(posting_id for roles, _ in answers for posting_id in roles))
    postings: list[Posting] = []
    skipped = max(without_id for _, without_id in answers)
    for posting_id in ids:
        versions = [p for roles, _ in answers if (p := roles.get(posting_id)) is not None]
        if not versions:
            skipped += 1
            continue
        postings.append(max(versions, key=lambda p: len(p.description)))
    return FetchResult(postings, skipped)
