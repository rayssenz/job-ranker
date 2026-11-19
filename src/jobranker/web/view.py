"""Small pure helpers that turn stored postings into what a card shows."""

from datetime import datetime, timedelta
from urllib.parse import urlsplit

from jobranker.models import Posting
from jobranker.profile import Profile
from jobranker.text import contains_phrase, normalise

EXCERPT_LIMIT = 280
NEW_FOR = timedelta(hours=24)
SOURCE_NAMES = {
    "greenhouse": "company page",
    "lever": "company page",
    "ashby": "company page",
    "linkedin": "LinkedIn",
}
_LINK_SCHEMES = frozenset({"http", "https"})


def excerpt(text: str, limit: int = EXCERPT_LIMIT) -> tuple[str, bool]:
    """The text on one line, cut at a word within the limit, and whether anything was cut."""
    line = " ".join(text.split())
    if len(line) <= limit:
        return line, False
    end = line.rfind(" ", 0, limit + 1)
    # A single word longer than the limit has no place to cut, so it is cut at the limit.
    return line[: end if end > 0 else limit], True


def safe_link(url: str) -> str | None:
    """The address when it is a plain web address with a host, else None.

    A posting comes from a third party, so its link could carry a script. Anything that is
    not `http` or `https` with a host is shown as text and never as a link.
    """
    address = url.strip()
    # A browser drops tabs and line breaks inside an address, which could hide a scheme.
    if not address or any(char.isspace() or not char.isprintable() for char in address):
        return None
    try:
        parts = urlsplit(address)
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme not in _LINK_SCHEMES or not host:
        return None
    return address


def age(first_seen: datetime, now: datetime) -> str:
    """How long ago a posting was first seen, in whole days."""
    days = (now - first_seen).days
    if days < 1:
        return "today"
    return "1 day ago" if days == 1 else f"{days} days ago"


def is_new(first_seen: datetime, now: datetime) -> bool:
    """Whether a posting was first seen in the last 24 hours."""
    return now - first_seen < NEW_FOR


def is_entry_level(title: str, profile: Profile) -> bool:
    """Whether the title holds a phrase from `levels.accept` of the profile."""
    words = normalise(title).split()
    return any(contains_phrase(words, phrase) for phrase in profile.levels.accept)


def matches(posting: Posting, query: str) -> bool:
    """Whether every word of the query is in the title, the company or the location."""
    text = " ".join(normalise(part) for part in (posting.title, posting.company, posting.location))
    return all(word in text for word in normalise(query).split())
