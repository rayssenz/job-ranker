"""A judge with fixed answers, for tests. It calls no model."""

from collections.abc import Mapping

from jobranker.judge import prompt
from jobranker.judge.base import Answer, JudgeFailure, to_verdict
from jobranker.models import Posting, Verdict
from jobranker.profile import Profile

_YES = Answer(decision="yes", reasons=["Fits the profile."], matched=[], missing=[])


class FakeJudge:
    """Answers by posting title, and with `default` for every other title."""

    def __init__(
        self,
        answers: Mapping[str, Answer | JudgeFailure] | None = None,
        default: Answer | None = None,
        model: str = "fake",
    ) -> None:
        self._answers = dict(answers or {})
        self._default = default or _YES
        self.model = model
        self.calls: list[Posting] = []

    def judge(self, posting: Posting, profile: Profile) -> Verdict:
        self.calls.append(posting)
        answer = self._answers.get(posting.title, self._default)
        if isinstance(answer, JudgeFailure):
            raise answer
        _, cut = prompt.build(posting, profile)
        return to_verdict(answer, cut=cut, model=self.model)
