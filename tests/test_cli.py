import os
import re
import sqlite3
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import httpx
import pytest
from support import TOKEN, Recorder, routes
from typer.testing import CliRunner

from jobranker import cli
from jobranker.cli import app

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
    assert len(result.output.splitlines()) == 5
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


def test_tracebacks_never_show_local_variables() -> None:
    assert app.pretty_exceptions_show_locals is False
