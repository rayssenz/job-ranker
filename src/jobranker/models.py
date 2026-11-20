"""The common posting record that every source produces."""

import hashlib
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from jobranker.text import normalise, normalise_company

_FIELD_SEPARATOR = "\x1f"


class Remote(StrEnum):
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


class Posting(BaseModel):
    """One job posting. `board` is empty for sources that have no board."""

    model_config = ConfigDict(frozen=True)

    source: str
    board: str
    posting_id: str
    company: str
    title: str
    location: str = ""
    remote: Remote = Remote.UNKNOWN
    url: str = ""
    description: str = ""

    @property
    def content_hash(self) -> str:
        parts = (self.title, self.location, self.remote.value, self.description)
        return hashlib.sha256(_FIELD_SEPARATOR.join(parts).encode()).hexdigest()

    @property
    def match_key(self) -> str:
        """Company and title in normalised form. Empty when either has no word left."""
        company, title = normalise_company(self.company), normalise(self.title)
        if not company or not title:
            return ""
        return f"{company}|{title}"


class Verdict(BaseModel):
    """What the judge said about one posting, and what the call used."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: Literal["yes", "no"]
    reasons: tuple[str, ...]
    matched: tuple[str, ...]
    missing: tuple[str, ...]
    # The description was longer than the judge reads and was cut.
    cut: bool
    model: str
    input_tokens: int
    output_tokens: int
    duration_ms: int
    # A notional figure from list prices. On a plan login it is not a charge.
    cost_usd: float
