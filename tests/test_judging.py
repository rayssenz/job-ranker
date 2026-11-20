from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jobranker import judging
from jobranker.judge.base import Answer, JudgeFailure, LimitReached
from jobranker.judge.fake import FakeJudge
from jobranker.judge.prompt import PROMPT_VERSION
from jobranker.judging import Tally
from jobranker.models import Posting, Verdict
from jobranker.profile import Profile
from jobranker.screening import apply_rules
from jobranker.store import Decision, Store, StoredPosting

T1 = datetime(2026, 11, 19, 8, 0, tzinfo=UTC)
PROFILE = Profile(places=["Lisbon"], skills=["Python"])
NO = Answer(decision="no", reasons=["Needs five years."], matched=[], missing=["experience"])
Report = list[tuple[str, str]]


def now() -> datetime:
    return T1 + timedelta(days=2)


def posting(number: int, location: str = "Lisbon") -> Posting:
    return Posting(
        source="greenhouse",
        board="northwindrobotics",
        posting_id=str(number),
        company="Northwind Robotics",
        title=f"Role {number}",
        location=location,
        description="Build models.",
    )


@pytest.fixture
def store(tmp_path: Path) -> Store:
    """Five postings that pass the rules, Role 5 the newest, and one that is dropped."""
    opened = Store(tmp_path / "ranker.db")
    for number in range(1, 6):
        opened.save(posting(number), T1 + timedelta(hours=number))
    opened.save(posting(9, "Madrid"), T1)
    apply_rules(opened, PROFILE, T1)
    return opened


def run(store: Store, judge: FakeJudge, limit: int = 40) -> tuple[Tally, Report]:
    seen: Report = []

    def report(stored: StoredPosting, outcome: Verdict | JudgeFailure) -> None:
        word = outcome.decision if isinstance(outcome, Verdict) else f"fail {outcome.reason}"
        seen.append((stored.posting.title, word))

    tally = judging.run(store, PROFILE, judge, limit=limit, now=now, report=report)
    return tally, seen


def titles(judge: FakeJudge) -> list[str]:
    return [called.title for called in judge.calls]


def verdicts(store: Store) -> dict[str, str]:
    groups = store.review_groups(PROFILE.digest, 1)
    found = store.current_verdicts([g.id for g in groups], PROFILE.judge_digest, PROMPT_VERSION)
    return {g.posting.title: found[g.id].decision for g in groups if g.id in found}


def test_every_waiting_group_is_judged_once_newest_first(store: Store) -> None:
    judge = FakeJudge({"Role 3": NO})
    tally, seen = run(store, judge)
    assert titles(judge) == ["Role 5", "Role 4", "Role 3", "Role 2", "Role 1"]
    assert tally == Tally(yes=4, no=1, failed=0, waiting=0, stopped=None)
    assert seen == [
        ("Role 5", "yes"),
        ("Role 4", "yes"),
        ("Role 3", "no"),
        ("Role 2", "yes"),
        ("Role 1", "yes"),
    ]
    assert verdicts(store)["Role 3"] == "no"
    assert len(verdicts(store)) == 5


def test_second_run_judges_nothing(store: Store) -> None:
    run(store, FakeJudge())
    again = FakeJudge()
    tally, seen = run(store, again)
    assert again.calls == []
    assert seen == []
    assert tally == Tally(yes=0, no=0, failed=0, waiting=0, stopped=None)


def test_limit_judges_the_newest_and_the_next_run_goes_on(store: Store) -> None:
    first = FakeJudge()
    tally, _ = run(store, first, limit=2)
    assert titles(first) == ["Role 5", "Role 4"]
    assert tally == Tally(yes=2, no=0, failed=0, waiting=3, stopped=None)
    second = FakeJudge()
    tally, _ = run(store, second, limit=2)
    assert titles(second) == ["Role 3", "Role 2"]
    assert tally.waiting == 1


def test_decided_group_is_not_judged(store: Store) -> None:
    newest = store.review_groups(PROFILE.digest, 1)[0]
    store.decide(newest.id, Decision.DISMISSED, T1)
    judge = FakeJudge()
    run(store, judge)
    assert "Role 5" not in titles(judge)
    assert len(judge.calls) == 4


def test_another_model_judges_everything_again(store: Store) -> None:
    run(store, FakeJudge(model="model-a"))
    other = FakeJudge(model="model-b")
    run(store, other)
    assert len(other.calls) == 5
    assert judging.waiting(store, PROFILE, "model-a") != []
    assert judging.waiting(store, PROFILE, "model-b") == []


def test_one_failure_stores_nothing_for_it_and_the_run_goes_on(store: Store) -> None:
    judge = FakeJudge({"Role 4": JudgeFailure("timeout")})
    tally, seen = run(store, judge)
    assert len(judge.calls) == 5
    assert tally == Tally(yes=4, no=0, failed=1, waiting=1, stopped=None)
    assert ("Role 4", "fail timeout") in seen
    assert "Role 4" not in verdicts(store)
    # The failed posting is tried again on the next run.
    again = FakeJudge()
    assert run(store, again)[0] == Tally(yes=1, no=0, failed=0, waiting=0, stopped=None)
    assert titles(again) == ["Role 4"]


def test_three_failures_in_a_row_stop_the_run(store: Store) -> None:
    failure = JudgeFailure("bad answer")
    judge = FakeJudge({"Role 4": failure, "Role 3": failure, "Role 2": failure})
    tally, _ = run(store, judge)
    assert titles(judge) == ["Role 5", "Role 4", "Role 3", "Role 2"]
    assert tally == Tally(yes=1, no=0, failed=3, waiting=4, stopped="failures")
    assert judging.FAILURES_IN_A_ROW == 3


def test_a_success_between_failures_starts_the_count_again(store: Store) -> None:
    failure = JudgeFailure("error")
    judge = FakeJudge({"Role 5": failure, "Role 4": failure, "Role 2": failure, "Role 1": failure})
    tally, _ = run(store, judge)
    assert len(judge.calls) == 5
    assert tally == Tally(yes=1, no=0, failed=4, waiting=4, stopped=None)


def test_reached_plan_limit_stops_at_once_and_keeps_what_was_stored(store: Store) -> None:
    judge = FakeJudge({"Role 3": LimitReached()})
    tally, seen = run(store, judge)
    assert titles(judge) == ["Role 5", "Role 4", "Role 3"]
    assert tally == Tally(yes=2, no=0, failed=0, waiting=3, stopped="plan limit")
    assert [title for title, _ in seen] == ["Role 5", "Role 4"]
    assert set(verdicts(store)) == {"Role 5", "Role 4"}
    later = FakeJudge()
    assert run(store, later)[0] == Tally(yes=3, no=0, failed=0, waiting=0, stopped=None)
    assert titles(later) == ["Role 3", "Role 2", "Role 1"]


def test_reached_spend_limit_is_named_as_such(store: Store) -> None:
    tally, _ = run(store, FakeJudge({"Role 5": LimitReached(spend=True)}))
    assert tally == Tally(yes=0, no=0, failed=0, waiting=5, stopped="spend limit")


def test_verdict_is_stored_before_the_next_call(store: Store) -> None:
    class Checking(FakeJudge):
        def judge(self, posting: Posting, profile: Profile) -> Verdict:
            # Every earlier posting of this run already has its verdict.
            assert len(verdicts(store)) == len(self.calls)
            return super().judge(posting, profile)

    run(store, Checking())
    assert len(verdicts(store)) == 5
