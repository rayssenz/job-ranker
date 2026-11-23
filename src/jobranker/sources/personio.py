"""Personio job feed. The public XML feed is `https://{token}.jobs.personio.de/xml`.

Personio holds each role's description in the language the company wrote it in. Asked in
the other language, the feed returns the same role with an almost empty description. The
feed is therefore read in German and in English, and each role keeps the version with more
description text, not counting the section headings.
"""

import xml.etree.ElementTree as ET
from xml.parsers import expat

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
# A role with its description text length, or None for a role without a title.
Role = tuple[Posting, int] | None


def fetch(client: httpx.Client, company: Company) -> FetchResult:
    answers: list[tuple[dict[str, Role], int]] = []
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


class _Declaration(Exception):
    pass


def _refuse_declarations(body: str) -> None:
    """Refuse a declared document type or entity.

    Either could make the reader load outside files or expand text without limit. Personio's
    feed has neither. The parser itself reports them, so text inside a description, such as a
    pasted `<!DOCTYPE html>` in a CDATA block, is not mistaken for one.
    """

    def refuse(*_: object) -> None:
        raise _Declaration

    parser = expat.ParserCreate()
    parser.StartDoctypeDeclHandler = refuse
    parser.EntityDeclHandler = refuse
    try:
        parser.Parse(body, True)
    except _Declaration:
        raise SourceError("unexpected shape") from None
    except expat.ExpatError:
        raise SourceError("not XML") from None


def _read(body: str, company: Company) -> tuple[dict[str, Role], int]:
    """The roles of one answer by ID and the number of roles without ID."""
    _refuse_declarations(body)
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise SourceError("not XML") from None
    if root.tag != ROOT:
        raise SourceError("unexpected shape")
    roles: dict[str, Role] = {}
    without_id = 0
    for position in root.iter("position"):
        posting_id = text(position.findtext("id"))
        if not posting_id:
            without_id += 1
            continue
        roles[posting_id] = _role(position, posting_id, company)
    return roles, without_id


def _role(position: ET.Element, posting_id: str, company: Company) -> Role:
    title = text(position.findtext("name"))
    if not title:
        return None
    offices = [
        position.findtext("office"),
        *(o.text for o in position.iterfind("additionalOffices/office")),
    ]
    location = places(offices)
    sections = [
        (text(entry.findtext("name")), html_to_text(entry.findtext("value") or ""))
        for entry in position.iterfind("jobDescriptions/jobDescription")
    ]
    description = "\n".join(part for section in sections for part in section if part)
    posting = Posting(
        source=SOURCE,
        board=company.token,
        posting_id=posting_id,
        company=company.name,
        title=title,
        location=location,
        remote=Remote.YES if "remote" in location.lower() else Remote.UNKNOWN,
        url=JOB_URL.format(token=company.token, id=posting_id),
        description=description,
    )
    return posting, sum(len(value) for _, value in sections)


def _merge(answers: list[tuple[dict[str, Role], int]]) -> FetchResult:
    """One posting per role ID, in order of first appearance, with more description text.

    On a tie the first language (German) is kept, so the choice is the same every run.
    """
    ids = list(dict.fromkeys(posting_id for roles, _ in answers for posting_id in roles))
    postings: list[Posting] = []
    skipped = max(without_id for _, without_id in answers)
    for posting_id in ids:
        versions = [r for roles, _ in answers if (r := roles.get(posting_id)) is not None]
        if not versions:
            skipped += 1
            continue
        postings.append(max(versions, key=lambda version: version[1])[0])
    return FetchResult(postings, skipped)
