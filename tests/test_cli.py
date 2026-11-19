import io
import os
import re
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import httpx
import pytest
from rich.console import Console
from support import TOKEN, Recorder, routes
from typer.testing import CliRunner

from jobranker import cli
from jobranker.cli import app
from jobranker.models import Posting
from jobranker.store import Store

runner = CliRunner()

ANSI_CODES = re.compile(r"\x1b\[[0-9;]*m")


def test_version_flag_prints_package_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"jobrank {version('jobranker')}"


def test_no_arguments_prints_help_and_exits_zero() -> None:
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    output = ANSI_CODES.sub("", result.stdout)
    assert "Usage" in output
    assert "Collect job postings" in output
    assert "--version" in output


def test_installed_jobrank_command_prints_version() -> None:
    command = Path(sys.executable).parent / "jobrank"
    result = subprocess.run(
        [str(command), "--version"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    assert result.stdout.strip() == f"jobrank {version('jobranker')}"


CONFIG = Path(__file__).resolve().parents[1] / "config"


def collect_args(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "collect",
        "--companies",
        str(CONFIG / "companies.example.yaml"),
        "--searches",
        str(tmp_path / "no-searches.yaml"),
        "--db",
        str(tmp_path / "data" / "ranker.db"),
        "--env-file",
        str(tmp_path / "no.env"),
        *extra,
    ]


def use_routes(monkeypatch: pytest.MonkeyPatch, recorder: Recorder) -> None:
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    monkeypatch.setattr(cli, "make_client", lambda: recorder.client)


def test_collect_prints_one_line_per_source_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_routes(monkeypatch, routes())
    result = runner.invoke(app, collect_args(tmp_path))
    assert result.exit_code == 0
    assert result.output.splitlines() == [
        "greenhouse Northwind Robotics: fetched 3, new 3, changed 0, duplicate 0",
        "lever      Bluefjord Labs: fetched 3, new 3, changed 0, duplicate 0",
        "ashby      Tessellate Systems: fetched 3, new 3, changed 0, duplicate 0",
        "Done in 0:00: 3 sources, 0 not collected, 9 new postings.",
    ]
    assert (tmp_path / "data" / "ranker.db").exists()


def test_collect_reads_searches_and_token_from_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = routes()
    use_routes(monkeypatch, recorder)
    env_file = tmp_path / ".env"
    env_file.write_text(f"APIFY_TOKEN={TOKEN}\n")
    args = collect_args(tmp_path, "--max-results", "60")
    args[args.index("--searches") + 1] = str(CONFIG / "searches.example.yaml")
    args[args.index("--env-file") + 1] = str(env_file)
    result = runner.invoke(app, args)
    assert result.exit_code == 0
    assert len(result.output.splitlines()) == 6
    assert "duplicate 1" in result.output
    assert TOKEN not in result.output
    apify = [r for r in recorder.requests if r.url.host == "api.apify.com"]
    assert [r.headers["Authorization"] for r in apify] == [f"Bearer {TOKEN}"] * 2


def test_collect_without_configuration_points_to_examples(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = routes()
    use_routes(monkeypatch, recorder)
    args = collect_args(tmp_path)
    args[args.index("--companies") + 1] = str(tmp_path / "no-companies.yaml")
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert "config/companies.example.yaml" in result.output
    assert "config/searches.example.yaml" in result.output
    assert recorder.requests == []
    assert not (tmp_path / "data").exists()


def test_collect_rejects_bad_configuration_before_any_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = routes()
    use_routes(monkeypatch, recorder)
    bad = tmp_path / "companies.yaml"
    bad.write_text("companies:\n  - name: Acme Test\n    feed: workday\n    token: acme\n")
    args = collect_args(tmp_path)
    args[args.index("--companies") + 1] = str(bad)
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert "Acme Test" in result.output
    assert recorder.requests == []
    assert not (tmp_path / "data").exists()


def test_collect_exits_one_when_every_source_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    down = Recorder(lambda request: httpx.Response(503, text="down"))
    use_routes(monkeypatch, down)
    result = runner.invoke(app, collect_args(tmp_path))
    assert result.exit_code == 1
    assert result.output.count("HTTP 503") == 3


def test_collect_exits_one_with_only_searches_and_no_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = routes()
    use_routes(monkeypatch, recorder)
    args = collect_args(tmp_path)
    args[args.index("--companies") + 1] = str(tmp_path / "no-companies.yaml")
    args[args.index("--searches") + 1] = str(CONFIG / "searches.example.yaml")
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert result.output.count("skipped: APIFY_TOKEN is not set") == 2
    assert recorder.requests == []


def test_collect_rejects_a_run_limit_below_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_routes(monkeypatch, routes())
    result = runner.invoke(app, collect_args(tmp_path, "--max-results", "0"))
    assert result.exit_code == 2


def test_real_client_has_a_timeout_and_names_the_program() -> None:
    with cli.make_client() as client:
        assert client.timeout.read == 20.0
        assert client.headers["User-Agent"] == f"jobranker/{version('jobranker')}"


def test_unusable_database_gives_a_short_message_without_the_token(tmp_path: Path) -> None:
    database = tmp_path / "old.db"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA user_version = 99")
    connection.close()
    command = Path(sys.executable).parent / "jobrank"
    result = subprocess.run(
        [str(command), *collect_args(tmp_path, "--db", str(database))],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "APIFY_TOKEN": TOKEN},
    )
    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "schema version 99" in " ".join(output.split())
    assert "Traceback" not in output
    assert TOKEN not in output


def test_database_path_that_is_a_folder_gives_a_short_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = routes()
    use_routes(monkeypatch, recorder)
    folder = tmp_path / "folder"
    folder.mkdir()
    result = runner.invoke(app, collect_args(tmp_path, "--db", str(folder)))
    assert result.exit_code == 1
    # An uncaught error also exits 1, so the kind of exit is checked as well.
    assert isinstance(result.exception, SystemExit)
    assert str(folder) in "".join(result.output.split())
    assert len(result.output.splitlines()) <= 3
    assert "Traceback" not in result.output
    assert recorder.requests == []


def test_tracebacks_never_show_local_variables() -> None:
    assert app.pretty_exceptions_show_locals is False


def test_unreadable_env_file_gives_a_short_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = routes()
    use_routes(monkeypatch, recorder)
    env_file = tmp_path / "bad.env"
    env_file.write_bytes(b"# caf\xe9\nAPIFY_TOKEN=abc\n")
    args = collect_args(tmp_path)
    args[args.index("--env-file") + 1] = str(env_file)
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert "bad.env" in result.output
    assert "Traceback" not in result.output
    assert recorder.requests == []


CONTROL_CHARACTER = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def searches_args(tmp_path: Path, *extra: str) -> list[str]:
    env_file = tmp_path / ".env"
    env_file.write_text(f"APIFY_TOKEN={TOKEN}\n")
    args = collect_args(tmp_path, *extra)
    args[args.index("--searches") + 1] = str(CONFIG / "searches.example.yaml")
    args[args.index("--env-file") + 1] = str(env_file)
    return args


def use_terminal(monkeypatch: pytest.MonkeyPatch) -> io.StringIO:
    screen = io.StringIO()
    console = Console(file=screen, force_terminal=True, width=100, color_system=None)
    monkeypatch.setattr(cli, "make_console", lambda: console)
    return screen


def test_plain_output_has_no_animation_and_ends_with_the_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_routes(monkeypatch, routes(lever=lambda r: httpx.Response(404)))
    result = runner.invoke(app, searches_args(tmp_path))
    assert result.exit_code == 0
    assert not CONTROL_CHARACTER.search(result.output)
    assert "Collecting" not in result.output
    lines = result.output.splitlines()
    assert lines[1] == "lever      Bluefjord Labs: HTTP 404"
    assert re.fullmatch(
        r"Done in \d+:\d\d: 5 sources, 1 not collected, \d+ new postings\.", lines[-1]
    )
    assert TOKEN not in result.output


def test_terminal_output_shows_the_bar_and_the_running_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_routes(monkeypatch, routes())
    screen = use_terminal(monkeypatch)
    result = runner.invoke(app, searches_args(tmp_path))
    assert result.exit_code == 0
    shown = screen.getvalue()
    assert "Collecting" in shown
    assert "0/5" in shown and "5/5" in shown
    assert "machine learning engineer / Lisbon" in shown
    assert "greenhouse Northwind Robotics: fetched 3, new 3, changed 0, duplicate 0" in shown
    assert re.search(r"Done in \d+:\d\d: 5 sources, 0 not collected, \d+ new postings\.", shown)
    assert TOKEN not in shown + result.output


def test_quiet_gives_plain_output_in_a_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_routes(monkeypatch, routes())
    screen = use_terminal(monkeypatch)
    result = runner.invoke(app, searches_args(tmp_path, "--quiet"))
    assert result.exit_code == 0
    shown = screen.getvalue() + result.output
    assert "Collecting" not in shown
    assert not CONTROL_CHARACTER.search(shown)
    assert len(shown.splitlines()) == 6


def test_each_line_is_written_before_the_next_source_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen_at_request: list[int] = []

    def counting(request: httpx.Request) -> httpx.Response:
        seen_at_request.append(len(capsys.readouterr().out.splitlines()))
        return httpx.Response(404)

    use_routes(monkeypatch, routes(greenhouse=counting, lever=counting, ashby=counting))
    with pytest.raises(SystemExit):
        app(collect_args(tmp_path))
    assert seen_at_request == [0, 1, 1]


PROFILE_TEXT = """
places: [Lisbon]
levels:
  accept: [junior]
  reject: [senior]
title_words: [engineer]
"""


def rules_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """A store with four made-up postings and a profile. Any request fails the test."""

    def no_requests() -> httpx.Client:
        raise AssertionError("this command must not send a request")

    monkeypatch.setattr(cli, "make_client", no_requests)
    database, profile = tmp_path / "ranker.db", tmp_path / "profile.yaml"
    profile.write_text(PROFILE_TEXT)
    rows = [
        ("1", "Junior Data Engineer", "Lisbon", datetime(2026, 11, 10, tzinfo=UTC)),
        ("2", "Senior Data Engineer", "Lisbon", datetime(2026, 11, 11, tzinfo=UTC)),
        ("3", "Barista", "Madrid", datetime(2026, 11, 12, tzinfo=UTC)),
        ("4", "Platform Engineer", "Lisbon Office", datetime(2026, 11, 13, tzinfo=UTC)),
    ]
    with Store(database) as store:
        for posting_id, title, location, seen in rows:
            posting = Posting(
                source="greenhouse",
                board="northwindrobotics",
                posting_id=posting_id,
                company="Northwind Robotics",
                title=title,
                location=location,
                url=f"https://example.test/jobs/{posting_id}",
            )
            store.save(posting, seen)
        copy = Posting(
            source="linkedin",
            board="",
            posting_id="900",
            company="Northwind Robotics",
            title="Platform Engineer",
            location="Lisbon, Portugal",
            url="https://example.test/copy/900",
        )
        store.save(copy, datetime(2026, 11, 14, tzinfo=UTC))
    return database, profile


def run_command(name: str, database: Path, profile: Path, *extra: str) -> list[str]:
    result = runner.invoke(app, [name, "--db", str(database), "--profile", str(profile), *extra])
    assert result.exit_code == 0, result.output
    return result.output.splitlines()


def test_rules_prints_counts_and_checks_nothing_the_second_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, profile = rules_setup(tmp_path, monkeypatch)
    assert run_command("rules", database, profile) == [
        "checked 5",
        "place: 1",
        "level: 1",
        "language: 0",
        "avoid: 0",
        "title: 1",
        "passed 3 postings in 2 groups",
    ]
    assert run_command("rules", database, profile)[0] == "checked 0"
    assert run_command("rules", database, profile)[-1] == "passed 3 postings in 2 groups"


def test_rules_checks_everything_again_after_a_profile_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, profile = rules_setup(tmp_path, monkeypatch)
    run_command("rules", database, profile)
    profile.write_text(PROFILE_TEXT.replace("title_words: [engineer]", "title_words: []"))
    lines = run_command("rules", database, profile)
    assert lines[0] == "checked 5"
    assert "title: 0" in lines


def test_list_prints_passed_groups_newest_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, profile = rules_setup(tmp_path, monkeypatch)
    run_command("rules", database, profile)
    assert run_command("list", database, profile) == [
        "Northwind Robotics | Platform Engineer | Lisbon Office",
        "  https://example.test/jobs/4",
        "Northwind Robotics | Junior Data Engineer | Lisbon",
        "  https://example.test/jobs/1",
    ]
    assert run_command("list", database, profile, "--limit", "1") == [
        "Northwind Robotics | Platform Engineer | Lisbon Office",
        "  https://example.test/jobs/4",
    ]


def test_list_can_be_limited_to_recent_days(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, profile = rules_setup(tmp_path, monkeypatch)
    run_command("rules", database, profile)
    monkeypatch.setattr(cli, "utc_now", lambda: datetime(2026, 11, 14, 12, tzinfo=UTC))
    assert len(run_command("list", database, profile, "--days", "2")) == 2
    assert len(run_command("list", database, profile, "--days", "30")) == 4


def test_list_before_rules_gives_a_hint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, profile = rules_setup(tmp_path, monkeypatch)
    assert run_command("list", database, profile) == [
        "No rule results for this profile. Run `jobrank rules` first."
    ]


@pytest.mark.parametrize("command", ["rules", "list"])
def test_missing_or_wrong_profile_stops_with_a_short_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    database, profile = rules_setup(tmp_path, monkeypatch)
    profile.unlink()
    result = runner.invoke(app, [command, "--db", str(database), "--profile", str(profile)])
    assert result.exit_code == 1
    assert "config/profile.example.yaml" in result.output
    profile.write_text("places: Lisbon-secret\n")
    result = runner.invoke(app, [command, "--db", str(database), "--profile", str(profile)])
    assert result.exit_code == 1
    assert "places" in result.output
    assert "secret" not in result.output and "Traceback" not in result.output
