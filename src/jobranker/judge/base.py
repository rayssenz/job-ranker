"""What every judge shares: the answer, the ways a call can fail and the interface."""

from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from jobranker.models import Posting, Verdict
from jobranker.profile import Profile

MAX_REASONS = 3
REASON_LENGTH = 300
MAX_REQUIREMENTS = 30
REQUIREMENT_LENGTH = 100

_Reason = Annotated[str, StringConstraints(min_length=1, max_length=REASON_LENGTH)]
_Requirement = Annotated[str, StringConstraints(max_length=REQUIREMENT_LENGTH)]


class Answer(BaseModel):
    """What the model has to return. Anything else is a failed call."""

    model_config = ConfigDict(extra="forbid", strict=True)

    decision: Literal["yes", "no"]
    reasons: list[_Reason] = Field(min_length=1, max_length=MAX_REASONS)
    matched: list[_Requirement] = Field(max_length=MAX_REQUIREMENTS)
    missing: list[_Requirement] = Field(max_length=MAX_REQUIREMENTS)


# The same limits in the form the model provider reads. Written out, so the text that goes
# over the wire does not change with a new version of a library.
_REQUIREMENTS: dict[str, Any] = {
    "type": "array",
    "maxItems": MAX_REQUIREMENTS,
    "items": {"type": "string", "maxLength": REQUIREMENT_LENGTH},
}
ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["decision", "reasons", "matched", "missing"],
    "properties": {
        "decision": {"type": "string", "enum": ["yes", "no"]},
        "reasons": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_REASONS,
            "items": {"type": "string", "minLength": 1, "maxLength": REASON_LENGTH},
        },
        "matched": _REQUIREMENTS,
        "missing": _REQUIREMENTS,
    },
}

# A failure is reported with one of these words and never with text from a posting or a model.
REASONS = frozenset({"timeout", "not JSON", "no answer", "bad answer", "error", "plan limit"})


class JudgeFailure(Exception):
    """One call gave no usable answer. The posting is judged again on a later run."""

    def __init__(self, reason: str) -> None:
        if reason not in REASONS:
            raise ValueError("a failure reason is one of the fixed words")
        super().__init__(reason)
        self.reason = reason


class LimitReached(JudgeFailure):
    """A usage limit of the account is reached, so no further call can succeed for now.

    `spend` is set when the limit is a spend limit. That limit exists only when the account
    pays for use beyond the plan.
    """

    def __init__(self, *, spend: bool = False) -> None:
        super().__init__("plan limit")
        self.spend = spend


class JudgeUnavailable(Exception):
    """The judge cannot start. The message is a fixed sentence that is shown to the user."""


class Judge(Protocol):
    """Anything that can give a verdict on one posting."""

    model: str

    def judge(self, posting: Posting, profile: Profile) -> Verdict: ...


def to_verdict(
    answer: Answer,
    *,
    cut: bool,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    duration_ms: int = 0,
    cost_usd: float = 0.0,
) -> Verdict:
    """The answer of the model together with what the call used."""
    return Verdict(
        decision=answer.decision,
        reasons=tuple(answer.reasons),
        matched=tuple(answer.matched),
        missing=tuple(answer.missing),
        cut=cut,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_ms=duration_ms,
        cost_usd=cost_usd,
    )
