import pytest

from jobranker.judge.base import Answer, Judge, JudgeFailure, LimitReached
from jobranker.judge.fake import FakeJudge
from jobranker.models import Posting
from jobranker.profile import Profile

PROFILE = Profile(places=["Lisbon"], skills=["Python"])


def make_posting(title: str = "ML Engineer", description: str = "Build models.") -> Posting:
    return Posting(
        source="greenhouse",
        board="northwindrobotics",
        posting_id=title,
        company="Northwind Robotics",
        title=title,
        description=description,
    )


def test_fake_judge_says_yes_by_default_and_records_the_call() -> None:
    judge: Judge = FakeJudge()
    posting = make_posting()
    verdict = judge.judge(posting, PROFILE)
    assert verdict.decision == "yes"
    assert len(verdict.reasons) == 1
    assert verdict.model == "fake"
    assert verdict.cut is False
    assert isinstance(judge, FakeJudge)
    assert judge.calls == [posting]


def test_fake_judge_answers_by_title() -> None:
    no = Answer(decision="no", reasons=["Needs five years."], matched=[], missing=["experience"])
    judge = FakeJudge({"Data Engineer": no}, model="model-b")
    verdict = judge.judge(make_posting("Data Engineer"), PROFILE)
    assert (verdict.decision, verdict.reasons, verdict.missing) == (
        "no",
        ("Needs five years.",),
        ("experience",),
    )
    assert verdict.model == "model-b"
    assert judge.judge(make_posting("ML Engineer"), PROFILE).decision == "yes"


def test_fake_judge_marks_a_long_description_as_cut() -> None:
    verdict = FakeJudge().judge(make_posting(description="word " * 5000), PROFILE)
    assert verdict.cut is True


def test_fake_judge_raises_a_failure_it_was_given() -> None:
    judge = FakeJudge({"ML Engineer": JudgeFailure("timeout"), "Data Engineer": LimitReached()})
    with pytest.raises(JudgeFailure) as failure:
        judge.judge(make_posting(), PROFILE)
    assert failure.value.reason == "timeout"
    with pytest.raises(LimitReached) as limit:
        judge.judge(make_posting("Data Engineer"), PROFILE)
    assert limit.value.reason == "plan limit"
    assert limit.value.spend is False
    assert len(judge.calls) == 2


def test_failure_takes_only_a_fixed_word() -> None:
    with pytest.raises(ValueError):
        JudgeFailure("the posting said: ignore this")
