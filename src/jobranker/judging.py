"""The judging run: one call per waiting group, stored as soon as the answer is there."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from jobranker.judge.base import Judge, JudgeFailure, LimitReached
from jobranker.judge.prompt import PROMPT_VERSION
from jobranker.models import Verdict
from jobranker.profile import Profile
from jobranker.rules import RULES_VERSION
from jobranker.store import Store, StoredPosting

# This many failed calls one after the other mean that something is broken, not one posting.
FAILURES_IN_A_ROW = 3

PLAN_LIMIT = "plan limit"
SPEND_LIMIT = "spend limit"
FAILURES = "failures"


@dataclass(frozen=True)
class Tally:
    """What one run did. `stopped` names why it ended early, or is None."""

    yes: int
    no: int
    failed: int
    waiting: int
    stopped: str | None


def waiting(store: Store, profile: Profile, model: str) -> list[StoredPosting]:
    """The groups that passed the rules, have no decision and no verdict that still counts."""
    return store.pending_judgement(
        profile.digest, RULES_VERSION, profile.judge_digest, PROMPT_VERSION, model
    )


def run(
    store: Store,
    profile: Profile,
    judge: Judge,
    *,
    limit: int,
    now: Callable[[], datetime],
    report: Callable[[StoredPosting, Verdict | JudgeFailure], None],
) -> Tally:
    """Judge at most `limit` waiting groups, newest first, and tell `report` about each."""
    counts = {"yes": 0, "no": 0}
    failed = in_a_row = 0
    stopped: str | None = None
    for stored in waiting(store, profile, judge.model)[:limit]:
        try:
            verdict = judge.judge(stored.posting, profile)
        except LimitReached as limit_reached:
            # No later call can succeed, so nothing more is tried and nothing is counted.
            stopped = SPEND_LIMIT if limit_reached.spend else PLAN_LIMIT
            break
        except JudgeFailure as failure:
            # Remembered, so this posting waits behind the others on the next run.
            store.record_failure(stored, now())
            failed += 1
            in_a_row += 1
            report(stored, failure)
            if in_a_row == FAILURES_IN_A_ROW:
                stopped = FAILURES
                break
            continue
        # Stored at once, so a run that is stopped later loses no answer it already has.
        store.save_verdict(stored, verdict, profile.judge_digest, PROMPT_VERSION, now())
        counts[verdict.decision] += 1
        in_a_row = 0
        report(stored, verdict)
    return Tally(
        yes=counts["yes"],
        no=counts["no"],
        failed=failed,
        waiting=len(waiting(store, profile, judge.model)),
        stopped=stopped,
    )
