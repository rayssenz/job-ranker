import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

from typer.testing import CliRunner

from jobranker.cli import app

runner = CliRunner()


def test_version_flag_prints_package_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"jobrank {version('jobranker')}"


def test_no_arguments_prints_help_and_exits_zero() -> None:
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "Usage" in result.stdout
    assert "Collect job postings" in result.stdout
    assert "--version" in result.stdout


def test_installed_jobrank_command_prints_version() -> None:
    command = Path(sys.executable).parent / "jobrank"
    result = subprocess.run(
        [str(command), "--version"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    assert result.stdout.strip() == f"jobrank {version('jobranker')}"
