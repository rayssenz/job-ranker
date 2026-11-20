"""The judge that asks Claude through Claude Code's non-interactive mode on a plan login."""

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from jobranker.judge import prompt
from jobranker.judge.base import (
    ANSWER_SCHEMA,
    Answer,
    JudgeFailure,
    JudgeUnavailable,
    LimitReached,
    to_verdict,
)
from jobranker.models import Posting, Verdict
from jobranker.profile import Profile

# A small, fast model, because it uses the least of the plan limit.
DEFAULT_MODEL = "claude-haiku-5-5"
TIMEOUT_SECONDS = 60.0
STATUS_TIMEOUT_SECONDS = 10.0

# With one of these set, Claude Code does not use the plan login and a call is billed.
BILLED_VARIABLES = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)

_LIMIT_START = "You've hit your"
# These limits exist only when the account pays for use beyond the plan.
_SPEND_WORDS = ("spend limit", "budget")
_NO_LOGIN = (
    "Claude Code is not signed in with a Claude plan. Run `claude auth login`,"
    " choose the plan account, and start the command again."
)


def check_ready(program: str = "claude", environ: Mapping[str, str] = os.environ) -> None:
    """Stop before the first call when it could not run, or would be billed on top of the plan."""
    if shutil.which(program) is None:
        raise JudgeUnavailable(
            "Claude Code is not installed, or `claude` is not on the path. The judge needs it."
        )
    for name in BILLED_VARIABLES:
        if environ.get(name):
            raise JudgeUnavailable(
                f"{name} is set, so Claude Code would not use the plan login and the calls"
                f" would be billed. Run `unset {name}` and start the command again."
            )
    try:
        done = subprocess.run(
            [program, "auth", "status"],
            capture_output=True,
            text=True,
            timeout=STATUS_TIMEOUT_SECONDS,
            check=False,
        )
        status = json.loads(done.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        raise JudgeUnavailable(_NO_LOGIN) from None
    plan_login = (
        isinstance(status, dict)
        and status.get("loggedIn") is True
        and status.get("authMethod") == "claude.ai"
        and status.get("apiProvider") == "firstParty"
    )
    if not plan_login:
        raise JudgeUnavailable(_NO_LOGIN)


def _number(value: object) -> float:
    # A bool is an int in Python and is no count.
    return value if isinstance(value, int | float) and not isinstance(value, bool) else 0


class ClaudeCodeJudge:
    """Runs `claude -p` once per posting, with no tools, no settings and no saved session."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        program: str = "claude",
        timeout: float = TIMEOUT_SECONDS,
    ) -> None:
        self.model = model
        self._program = program
        self._timeout = timeout

    def _command(self) -> list[str]:
        return [
            self._program,
            "-p",
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(ANSWER_SCHEMA),
            # No tools: the model can read no file and run no command.
            "--tools",
            "",
            "--no-session-persistence",
            # No user or project settings, so no hook and no server is loaded.
            "--setting-sources",
            "",
            "--system-prompt",
            prompt.SYSTEM,
            "--model",
            self.model,
        ]

    def judge(self, posting: Posting, profile: Profile) -> Verdict:
        text, cut = prompt.build(posting, profile)
        # The posting goes in on standard input and never on the command line, where other
        # programs of the machine could read it. The folder is empty, so nothing of a project
        # is found from it.
        try:
            with tempfile.TemporaryDirectory() as folder:
                done = subprocess.run(
                    self._command(),
                    input=text,
                    capture_output=True,
                    text=True,
                    cwd=folder,
                    timeout=self._timeout,
                    check=False,
                )
        except subprocess.TimeoutExpired:
            raise JudgeFailure("timeout") from None
        except (OSError, subprocess.SubprocessError):
            raise JudgeFailure("error") from None
        return self._read(done.stdout, cut)

    def _read(self, output: str, cut: bool) -> Verdict:
        # A failure inside the run is printed as the result, so the output is read whatever
        # the exit code was. Nothing of it is put into a failure.
        try:
            result: Any = json.loads(output)
        except ValueError:
            raise JudgeFailure("not JSON") from None
        if not isinstance(result, dict):
            raise JudgeFailure("not JSON")
        if result.get("is_error"):
            message = result.get("result")
            if isinstance(message, str) and message.startswith(_LIMIT_START):
                raise LimitReached(spend=any(word in message for word in _SPEND_WORDS))
            raise JudgeFailure("error")
        if result.get("structured_output") is None:
            raise JudgeFailure("no answer")
        try:
            answer = Answer.model_validate(result["structured_output"])
        except ValidationError:
            raise JudgeFailure("bad answer") from None
        usage = result.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        return to_verdict(
            answer,
            cut=cut,
            model=self.model,
            input_tokens=int(
                _number(usage.get("input_tokens"))
                + _number(usage.get("cache_creation_input_tokens"))
                + _number(usage.get("cache_read_input_tokens"))
            ),
            output_tokens=int(_number(usage.get("output_tokens"))),
            duration_ms=int(_number(result.get("duration_ms"))),
            cost_usd=float(_number(result.get("total_cost_usd"))),
        )
